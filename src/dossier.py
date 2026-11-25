"""Bone Fides dossier logic: the single source for both web runtimes.

ui/server.py (local demo) and vercel-app/api/search.py (deployed function) are
thin HTTP adapters around dispatch(). They used to be hand-kept copies of this
module; now there is one implementation and nothing to keep in parity.

Stdlib plus the elasticsearch client only. build.sh copies this file, its
sibling imports, and the data files it reads into vercel-app/api/_lib/, so
imports between them must stay relative.
"""
import datetime
import json
import os
import re
import time
import traceback
from urllib.parse import parse_qs

from .es_query import INDEX, TIPS_INDEX, ensure_tips_index, find_edges, make_client  # noqa: F401
from .roles import role_bucket
from .venue_aliases import identity as _venue_identity, identity_words as _venue_identity_words

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_UI = os.path.join(os.path.dirname(_HERE), "ui")


def data_path(name):
    """Runtime data file: beside this module in the Vercel bundle, ui/ in a checkout."""
    bundled = os.path.join(_HERE, name)
    return bundled if os.path.exists(bundled) else os.path.join(_REPO_UI, name)


def venue_key(v):
    return _venue_identity(v)


def venue_key_words(v):
    return _venue_identity_words(v)


# Field coverage the /method page documents. Cached with stats(): the counts
# move only when the corpus does, and the page is opened far more often than
# the corpus is rebuilt.
_METHOD_CACHE = {"at": 0.0, "value": None}
_COVERAGE_FIELDS = ("date", "era_bucket", "venue_hoods", "action", "mentor")


def method(es):
    """Corpus composition for the /method page: coverage rates and outlet tiers.

    Every figure here is a live measurement — the page's whole purpose is to
    state what the corpus actually contains, so nothing on it may be estimated.
    Counts that also appear on the landing page come from stats() so the two
    pages cannot disagree.
    """
    now = time.time()
    cached = _METHOD_CACHE["value"]
    if cached is not None and now - _METHOD_CACHE["at"] < _STATS_TTL:
        return cached

    base = stats(es)
    agg_body = {"size": 0, "aggs": {}}
    for f in _COVERAGE_FIELDS:
        agg_body["aggs"][f] = {"filter": {"exists": {"field": f}}}
    # Outlet tiers must use the SAME rule the score uses: outlet_tier(), which
    # falls back to the source_url host when `source` is missing. A pure
    # `term: source` aggregation would count the 23 host-identifiable edges
    # with no `source` as "other" while the score counted them as Eater.
    agg_body["aggs"]["tiers"] = {"terms": {"field": "source", "size": 10}}
    a = es.search(index=INDEX, body=agg_body)["aggregations"]

    coverage = dict(base)
    for f in _COVERAGE_FIELDS:
        coverage[f] = a[f]["doc_count"]

    tiers = {"sfchronicle": 0, "sfgate": 0, "eater": 0, "other": 0}
    for b in a["tiers"]["buckets"]:
        key = b["key"] if b["key"] in tiers else "other"
        tiers[key] += b["doc_count"]
    # edges with no `source` still have a host; classify them the way the
    # score does rather than dumping them into "other". The terms agg above
    # only saw edges that HAVE a source, so these are purely additive.
    for h in es.search(index=INDEX, body={
            "size": 1000,
            "query": {"bool": {"must_not": {"exists": {"field": "source"}}}},
            "_source": ["source", "source_url"]})["hits"]["hits"]:
        src = h["_source"]
        tiers[outlet_tier(src.get("source"), src.get("source_url"))] += 1
    value = {"coverage": coverage, "tiers": tiers,
             "scores": _score_sample()}
    _METHOD_CACHE["at"], _METHOD_CACHE["value"] = now, value
    return value


# A fixed sample so the published score distribution is reproducible across
# runs. Deliberately well-documented, recognizable kitchens: the point is to
# show a reader what the scale looks like on the best-reported records, not to
# claim this is the corpus distribution (most venues score far lower).
_SCORE_SAMPLE = (
    "SPQR", "State Bird Provisions", "Chez Panisse", "Mister Jiu's", "Quince",
    "Zuni Cafe", "Delfina", "Benu", "Mourad", "Betelnut", "Tartine",
    "Kin Khao", "Lazy Bear", "Coi", "Saison", "Nopa", "Rich Table",
    "Atelier Crenn",
)


def measure_score_sample(es):
    """MEASURE the score distribution across _SCORE_SAMPLE. Slow (~7s).

    This is the computing half, kept separate from _score_sample() (the cheap
    file reader the web request uses) because the two have opposite cost and
    call-site profiles: this one runs offline in stamp_score_sample.py, the
    other runs on every cold serverless instance.

    Not called at request time by design. Never wire this into a handler.

    Scores come from assemble_dossier(), the explorer's own path, NOT from
    scoring raw search hits. Hybrid search returns fuzzy and related matches,
    and assemble_dossier applies scope_edges() to drop the ones that are not
    actually about the queried kitchen before scoring. Skipping that step
    published numbers the dossiers themselves did not show: 6 of the 18
    sampled kitchens disagreed, Tartine by 10 points and Atelier Crenn by 21.

    A failed search is a failure, not a smaller sample. Silently dropping a
    kitchen would let a transient timeout redefine the "fixed" sample and
    overwrite the saved stamp with a different range. If any kitchen cannot be
    scored, return None and let the caller keep the existing file.
    """
    scores = []
    for name in _SCORE_SAMPLE:
        try:
            lin = lineage(es, name, size=25)
            ped = (assemble_dossier(name, lin, es=es) or {}).get("pedigree")
        except Exception as exc:
            print(f"score sample: {name!r} failed ({type(exc).__name__}) — "
                  f"leaving the saved stamp untouched")
            return None
        if not ped:
            print(f"score sample: {name!r} has no scored dossier — "
                  f"leaving the saved stamp untouched")
            return None
        scores.append(ped["score"])
    if not scores:
        return None
    scores.sort()
    mid = len(scores) // 2
    median = scores[mid] if len(scores) % 2 else round(
        (scores[mid - 1] + scores[mid]) / 2)
    return {"n": len(scores), "min": scores[0], "max": scores[-1],
            "median": median}


def _score_sample(_data_path=None):
    """The published score distribution, read from a stamped data file.

    Measured offline by src/stamp_score_sample.py rather than computed per
    request: assembling 18 dossiers costs ~7s, which every cold serverless
    instance would pay before the page could render a number. The sample is
    fixed, so the result is stable; re-stamp it after a corpus-growth run.

    Returns None (and the page falls back to its own copy) if the file is
    missing — a deploy without the stamp should degrade, not 500.
    """
    path = _data_path or data_path("score_sample.json")
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or "min" not in d:
        return None
    return d

MAX_QUERY_LEN = 120  # abuse cap: queries are names, not free-text essays
MAX_RESULT_SIZE = 40  # a dossier, not a corpus dump

TIP_TYPES = ("wrong person", "wrong venue", "wrong detail",
             "add a move", "add a source")
MAX_TIP_NOTE = 500
MAX_TIP_URL = 300

def accept_tip(payload, ip):
    """Validate a reader-submitted correction/tip into a storable doc.

    Returns (ok, doc_or_error); doc_or_error is None when the tip is
    accepted but must not be stored (honeypot). Source URL is required
    for the two "grow the corpus" types — a tip that adds a move or
    source without a citation is not actionable, and citations are the
    product."""
    if not isinstance(payload, dict):
        return False, "invalid payload"
    if (payload.get("website") or "").strip():
        # Honeypot filled: bots only. Accept silently, store nothing.
        return True, None
    ttype = (payload.get("type") or "").strip().lower()
    if ttype not in TIP_TYPES:
        return False, "unknown type"
    note = (payload.get("note") or "").strip()[:MAX_TIP_NOTE]
    url = (payload.get("url") or "").strip()[:MAX_TIP_URL]
    if ttype in ("add a move", "add a source"):
        if not url or not re.match(r"https?://", url):
            return False, "a source link is required to add to the record"
    if not note and not url:
        return False, "a note or a source link is required"
    doc = {
        "query": (payload.get("query") or "").strip()[:MAX_QUERY_LEN],
        "context": (payload.get("context") or "").strip()[:MAX_QUERY_LEN],
        "person": (payload.get("person") or "").strip()[:80],
        "venue": (payload.get("venue") or "").strip()[:80],
        "type": ttype,
        "url": url,
        "note": note,
        "ip": ip,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "open",
    }
    return True, doc


TIER_WEIGHT = {"sfchronicle": 12, "sfgate": 8, "eater": 6}

_BUCKETS = {}

def allow_request(bucket, key, limit, window, now=None):
    now = time.time() if now is None else now
    slot = _BUCKETS.setdefault(bucket, {})
    hits = [t for t in slot.get(key, []) if now - t < window]
    if len(hits) >= limit:
        slot[key] = hits
        return False
    hits.append(now)
    slot[key] = hits
    if len(slot) > 4000:
        stale = [k for k, v in slot.items() if not v or now - v[-1] >= window]
        for k in stale:
            slot.pop(k, None)
    return True

def clamp_size(raw, default=25):
    """Public page size. Non-integers raise so the handler can stay generic."""
    if raw in (None, "", []):
        return default
    n = int(raw)
    return min(MAX_RESULT_SIZE, max(1, n))

def _is_collective(name):
    """Anonymous/collective entity ("chefs", "sous chef", "two chefs"): the
    corpus honestly records unnamed people, but they are not a chef NAMED
    the query, so they must not resolve it. A string resolves as a person
    only if some capitalized token survives stopword stripping."""
    n = re.sub(r'"[^"]*"', '', name or "")
    n = re.sub(r"\([^)]*\)", '', n)
    tokens = [t for t in re.split(r"[\s+'’-]+", n) if t]
    named = [t for t in tokens if t[:1].isupper() and t.lower() not in
             ("chef", "chefs", "the", "a", "an", "former", "new", "same",
              "unknown", "unnamed", "top")]
    return not named


def norm_name(n):
    """Canonical person-name key: drop quoted nicknames, straighten quotes,
    lowercase, strip punctuation. 'Traci des Jardins' == 'Traci Des Jardins',
    "Sean O'Brien" == 'Sean O’Brien', "Thitid 'Ton' Tassanakajohn" collapses."""
    n = re.sub(r'"[^"]*"', '', n)
    n = n.replace(chr(8217), "'").replace(chr(8216), "'")
    n = n.replace(chr(8220), "'").replace(chr(8221), "'")  # curly double -> straight
    n = re.sub(r"'[^']*'", '', n)
    n = re.sub(r'[^a-z\s-]', '', n.lower())
    return ' '.join(n.split())

def _keysplit(key):
    """(first, last) tokens of a normalized person key, or (None, None)."""
    t = key.split()
    return (t[0], t[-1]) if len(t) >= 2 else (None, None)

_NICKNAMES = {
    "jen": "jennifer", "jennifer": "jen",
    "josh": "joshua", "joshua": "josh",
    "chris": "christopher", "christopher": "chris",
    "alex": "alexander", "alexander": "alex",
    "mike": "michael", "michael": "mike",
    "rob": "robert", "robert": "rob", "bob": "robert",
    "dan": "daniel", "daniel": "dan",
    "dave": "david", "david": "dave",
    "matt": "matthew", "matthew": "matt",
    "nick": "nicholas", "nicholas": "nick",
    "tom": "thomas", "thomas": "tom",
    "sam": "samuel", "samuel": "sam",
    "pat": "patrick", "patrick": "pat",
    "liz": "elizabeth", "elizabeth": "liz",
    "kate": "katherine", "katherine": "kate",
    "bill": "william", "will": "william", "william": "bill",
    "jim": "james", "james": "jim",
    "joe": "joseph", "joseph": "joe",
    "tony": "anthony", "anthony": "tony",
    "steve": "steven", "steven": "steve", "stephen": "steve",
    "andy": "andrew", "andrew": "andy",
    "ben": "benjamin", "benjamin": "ben",
    "jon": "jonathan", "jonathan": "jon",
}

def _fuzzy_sibling(ka, kb):
    """Same surname and a known nickname pair (Jen/Jennifer, Chris/Christopher).
    Prefix overlap alone is not enough — Dan is not Danielle."""
    fa, la = _keysplit(ka)
    fb, lb = _keysplit(kb)
    if not fa or not fb or la != lb or fa == fb:
        return False
    return _NICKNAMES.get(fa) == fb or _NICKNAMES.get(fb) == fa

def norm_venue(v):
    """Normalized venue key for overlap matching only (never displayed):
    drop parenthetical annotations (Saison (2124 Folsom St.) == Saison),
    trailing possessives (Chez TJ's == Chez TJ), unicode-fold accents
    (Jardinière == Jardiniere), straighten apostrophes, strip punctuation,
    drop stop words (The Commissary == Commissary).

    Kept for the legacy overlap-matching path. COUNTING uses venue_key().
    """
    import unicodedata as _ud
    v = re.sub(r'\([^)]*\)', ' ', v)                      # (Folsom St. location)
    v = _ud.normalize("NFD", v)
    v = "".join(ch for ch in v if not _ud.combining(ch))
    v = v.replace(chr(8217), "'").replace(chr(8216), "'")
    v = re.sub(r"['’]s?\b", '', v)                        # possessive TJ's -> TJ
    v = re.sub(r'[^a-z0-9\s]', '', v.lower())
    toks = [t for t in v.split() if t not in ("the", "a", "an", "of", "at", "in", "on")]
    return ' '.join(toks)


_GENERIC_VENUE = {"bar", "cafe", "kitchen", "grill", "house", "restaurant",
                  "room", "club", "san", "sf", "food", "wine", "bakery",
                  "café", "taqueria", "pizzeria"}

def _venue_touch(va, vb):
    """Exact identity match, or the shorter is a whole-token prefix of the
    longer (Betelnut ⊂ Betelnut Pejiu Wu). A single generic token does not
    match.

    Both sides are venue_key_words() output, so they keep spaces. That is the
    whole point: the squashed identity makes "elfaro" a character prefix of
    "elfarolito", which joined El Faro and El Farolito into one career and hid
    the "these may be different people" warning. Comparing TOKENS requires the
    boundary to be a real one.
    """
    if va == vb:
        return True
    ta, tb = va.split(), vb.split()
    if not ta or not tb:
        return False
    if len(ta) > len(tb):
        ta, tb = tb, ta
    if tb[:len(ta)] != ta:
        return False
    if len(ta) == 1 and (ta[0] in _GENERIC_VENUE or len(ta[0]) < 4):
        return False
    return True

def _venues_touch(sa, sb):
    """Any pair of venue keys across two sets touches."""
    return any(_venue_touch(a, b) for a in sa for b in sb)

def venue_history(edges):
    """Set of venue IDENTITIES an edge set touches (from_venue + to_venue).

    Word-preserving form, because matching needs boundaries. Exact-identity
    collapsing (the owner's rulings, accents, a leading "The") still happens
    first, so "Michael Mina" and "Restaurant Michael Mina" land on one token
    string and reach the same dossier.
    """
    v = set()
    for e in edges:
        for k in ("from_venue", "to_venue"):
            if e.get(k):
                v.add(venue_key_words(e[k]))
    return v

def edge_urls(edges):
    """Set of source URLs an edge set cites (same article = same subject)."""
    return {e["source_url"] for e in edges if e.get("source_url")}

def _components(edges):
    """Connected components over one name-key's edges. Two edges join when they
    share a venue string (normalized) or a source URL (same article = same
    subject). Returns [{names, edges, venues, urls}, ...]."""
    comps = []
    for e in edges:
        vv = venue_history([e])
        uu = edge_urls([e])
        placed = False
        for c in comps:
            if _venues_touch(c["venues"], vv) or c["urls"] & uu:
                c["names"].add(e["person"]); c["edges"].append(e)
                c["venues"] |= vv; c["urls"] |= uu
                placed = True
                break
        if not placed:
            comps.append({"names": {e["person"]}, "edges": [e],
                          "venues": set(vv), "urls": set(uu)})
    changed = True
    while changed:  # transitive closure: an edge can bridge two components
        changed = False
        for i in range(len(comps)):
            for j in range(i + 1, len(comps)):
                if _venues_touch(comps[i]["venues"], comps[j]["venues"]) \
                        or comps[i]["urls"] & comps[j]["urls"]:
                    comps[i]["names"] |= comps[j]["names"]
                    comps[i]["edges"] += comps[j]["edges"]
                    comps[i]["venues"] |= comps[j]["venues"]
                    comps[i]["urls"] |= comps[j]["urls"]
                    del comps[j]
                    changed = True
                    break
            if changed:
                break
    return comps

def identity(edges):
    """People disambiguation for the dossier.

    1. Group edges by normalized person name (case/quote/nickname variants).
    2. Within a name key, split into components connected by shared venues or
       shared source articles. One big component + lone single-mention
       singletons folds to one card (a lone mention is not evidence of a
       second chef). Only when two or more MULTI-EDGE components stay
       unconnected do both get homonym=True — possibly two different people,
       surfaced, not silently merged.
    3. Across different name keys, initial-prefix siblings (Jennifer/Jen
       Biesty) merge when venue/article histories overlap; otherwise both
       sides carry possible=[other name] — 'possibly the same chef'.
    """
    groups = {}
    for e in edges:
        p = e.get("person")
        if not p:
            continue
        groups.setdefault(norm_name(p), []).append(e)

    clusters = []
    for key, g in groups.items():
        comps = _components(g)
        comps.sort(key=lambda c: -len(c["edges"]))
        big, rest = comps[0], comps[1:]
        split = [c for c in rest if len(c["edges"]) >= 2]
        lone = [c for c in rest if len(c["edges"]) < 2]
        # lone mentions fold into the largest component; real splits stay out
        for c in lone:
            big["names"] |= c["names"]; big["edges"] += c["edges"]
            big["venues"] |= c["venues"]; big["urls"] |= c["urls"]
        big["homonym"] = bool(split)
        for c in split:
            c["homonym"] = True
            clusters.append({"key": key, **c})
        clusters.append({"key": key, **big})

    # fuzzy siblings across keys: merge on venue/article overlap, else flag
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                a, b = clusters[i], clusters[j]
                # same names-guard as the flag pass below: clusters sharing a
                # person string are the homonym case (already flagged), not
                # two name variants of one chef. Merging them here would
                # collapse "possibly two people" into a single card and
                # silently assert an identity the corpus cannot support.
                if a["key"] != b["key"] and not (a["names"] & b["names"]) \
                        and _fuzzy_sibling(a["key"], b["key"]) \
                        and (_venues_touch(a["venues"], b["venues"]) or a["urls"] & b["urls"]):
                    a["names"] |= b["names"]; a["edges"] += b["edges"]
                    a["venues"] |= b["venues"]; a["urls"] |= b["urls"]
                    a["key"] = a["key"] if len(a["key"]) >= len(b["key"]) else b["key"]
                    a["homonym"] = a.get("homonym") or b.get("homonym", False)
                    del clusters[j]
                    merged = True
                    break
            if merged:
                break
    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            a, b = clusters[i], clusters[j]
            # skip pairs sharing a person string: that is the homonym case,
            # already flagged — cross-referencing variant names here only
            # produces self-referential badges ("possibly Chris Fernandez"
            # on a card already named Chris Fernandez)
            if a["key"] != b["key"] and not (a["names"] & b["names"]) \
                    and _fuzzy_sibling(a["key"], b["key"]):
                a.setdefault("possible", set()).add(max(b["names"], key=len))
                b.setdefault("possible", set()).add(max(a["names"], key=len))

    out = []
    for c in clusters:
        counts = {}
        for e in c["edges"]:
            counts[e["person"]] = counts.get(e["person"], 0) + 1
        name = max(sorted(c["names"]), key=lambda n: counts[n])  # most-cited variant
        aliases = sorted(n for n in c["names"] if n != name)
        out.append({"name": name, "aliases": aliases,
                    "homonym": bool(c.get("homonym")),
                    "possible": sorted(c.get("possible", ())),
                    "n": len(c["edges"]), "edges": c["edges"]})
    out.sort(key=lambda c: -c["n"])
    return out

# Career-move language. Plain career facts the extraction prompt asks for —
# "worked at Betelnut", "worked under Thomas Keller", "trained at French
# Laundry" — are accepted: they are the mentor/stint sentences of a lineage.
# A recipe sentence that merely names a title ("combines it with butter")
# is not a promotion.
_MOVE_CUE = re.compile(
    r"\b(join(?:ed|s|ing)?|depart(?:ed|s|ure)?|leav(?:e|es|ing)|left|"
    r"hir(?:ed|es|ing)|appoint(?:ed|s|ment)?|t(?:ook|akes|aking) over|"
    r"mov(?:e|ed|es|ing) (?:over|to|from)|jumped ship|"
    r"promot(?:ed|es|ion)|elevat(?:ed|es|ion)|"
    r"named (?:culinary|executive|the new|as the|director|chef)|"
    r"new executive chef|"
    r"opens?|opened|founded|exit(?:ed|s|ing)?|steps down|"
    r"headed to|lands? at|came from|coming from|went on|goes to|"
    r"now (?:at|runs|heads)|formerly|previously|"
    r"work(?:ed|s|ing) (?:at|under|for|with|in)|"
    r"train(?:ed|s|ing) (?:at|under|with)|apprenticed? (?:at|under|with)|"
    r"staged (?:at|under|with)|cook(?:ed|ing) (?:at|for|under)|"
    r"sous chef under|tenure (?:at|with)|spent .* (?:at|with))\b",
    re.I)
_PROMO_CUE = re.compile(
    r"\b(promot(?:ed|es|ion)|elevat(?:ed|es|ion)|"
    r"named (?:executive|the new|as the)|appointed (?:executive|chef|as)|"
    r"rises to|steps up to|new title)\b",
    re.I)
_NONCAREER = re.compile(
    r"\b(guest chefs?|pop-?ups?|suppliers?|purveyors?|vendors?)\b", re.I)

def citation_supported(edge):
    """True when the stored quotation itself states a career move.

    Indexed edges are not re-fetched. PROMOTED is kept only when the
    quotation says so; guest shifts and supplier blurbs are not moves.
    """
    ev = (edge.get("evidence") or "").strip()
    if not ev:
        return False
    role = edge.get("role") or ""
    if _NONCAREER.search(role) or _NONCAREER.search(ev):
        return False
    action = (edge.get("action") or "").upper()
    if action == "PROMOTED":
        return bool(_PROMO_CUE.search(ev))
    return bool(_MOVE_CUE.search(ev))

def outlet_tier(source, url):
    """sfchronicle | sfgate | eater | other. A null or mismatched source
    never borrows the Eater label from a different host."""
    host = ""
    if url:
        m = re.search(r"https?://([^/]+)", url, re.I)
        host = (m.group(1) if m else "").lower()
    if source == "eater" and host and "eater" not in host:
        source = None
    if source in TIER_WEIGHT:
        return source
    if "sfchronicle" in host:
        return "sfchronicle"
    if "sfgate" in host:
        return "sfgate"
    if "eater.com" in host or host.startswith("eater.") or ".eater." in host:
        return "eater"
    return "other"

def _loose(s):
    """Punctuation-loose comparison key: lowercase letters and digits only.
    "Mister Jiu's" and "Mister Jius" are the same kitchen to a reader who
    skipped the apostrophe; "flour+water" and "flour water" likewise."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

# the bucket vocabulary the &role= facet accepts (src.roles.BUCKETS twin)
_ROLE_BUCKETS = {"chef", "executive chef", "pastry", "sous", "owner", "bartender", "other"}
# era + hood vocabularies (roadmap 4.4, src.eras.ERA_BUCKETS and
# src.hoods.hood_vocabulary twins). Hoods mirror the city file's
# analysis_neighborhood labels — the exact list is locked by test.
_ERA_BUCKETS = {"pre-1990", "1990s", "2000s", "2010s", "2020s"}
_HOOD_VOCAB = {
    "Bayview Hunters Point", "Bernal Heights", "Castro/Upper Market",
    "Chinatown", "Excelsior", "Financial District/South Beach", "Glen Park",
    "Golden Gate Park", "Haight Ashbury", "Hayes Valley", "Inner Richmond",
    "Inner Sunset", "Japantown", "Lakeshore", "Lincoln Park",
    "Lone Mountain/USF", "Marina", "McLaren Park", "Mission", "Mission Bay",
    "Nob Hill", "Noe Valley", "North Beach", "Oceanview/Merced/Ingleside",
    "Outer Mission", "Outer Richmond", "Pacific Heights", "Portola",
    "Potrero Hill", "Presidio", "Presidio Heights", "Russian Hill",
    "Seacliff", "South of Market", "Sunset/Parkside", "Tenderloin",
    "Treasure Island", "Twin Peaks", "Visitacion Valley",
    "West of Twin Peaks", "Western Addition",
}
# coverage notes travel with every facet-filtered payload (the corpus's dates
# and SF-placeable venues are partial; the filter must say so).
# NOTE: these strings describe the RAW field coverage — dates are present on
# ~15.6% of edges, neighborhood stamps on ~41% — but the era filter itself
# runs on era_bucket, which only 12.5% of edges carry (a date that yields no
# citable year gets no bucket). The era note therefore overstates what the
# filter can see by ~3 points. Tighten both strings to the filter's real
# reach when the methodology page lands.
_ERA_COVERAGE = "dates on 15% of cited moves"
_HOOD_COVERAGE = "neighborhoods on 43% of cited moves"


def _same_loose(a, b):
    """Loose equality, gated like the prefix rule: short keys absorb too much."""
    la, lb = _loose(a), _loose(b)
    return bool(la and len(la) >= 4 and la == lb)

def _venue_matches_query(ql, venue):
    """Same resolution rule as resolve_query: exact, punctuation-loose, or a
    >=4 char prefix."""
    if not venue:
        return False
    vl = venue.lower().strip()
    if vl == ql:
        return True
    if _same_loose(vl, ql):
        return True
    return bool(len(ql) >= 4 and len(vl) >= 4 and (vl.startswith(ql) or ql.startswith(vl)))

def scope_edges(q, lin, cl):
    """Edges that belong to the resolved chef or kitchen, not the rest of the page."""
    ql = (q or "").lower().strip()
    person_edges = []
    for c in cl:
        names = [c["name"], *(c.get("aliases") or [])]
        if any(((n or "").lower() == ql or _same_loose(n, ql))
               and not _is_collective(n) for n in names):
            person_edges.extend(c["edges"])
    # The person-vs-venue comparison counts only OTHER chefs' venue hits: a
    # namesake restaurant touched by the queried chef's own moves must not
    # tip the count toward the venue bucket (the explorer's venueFlips filter
    # skips the queried person for the same reason). But when the venue wins
    # the comparison, the returned restaurant dossier keeps every venue edge
    # — the chef's own moves are part of the restaurant's record too.
    person_set = {e.get("person") for e in person_edges}
    venue_edges = [e for e in lin
                   if _venue_matches_query(ql, e.get("from_venue"))
                   or _venue_matches_query(ql, e.get("to_venue"))]
    competing = sum(1 for e in venue_edges if e.get("person") not in person_set)
    # A person whose own record is at least as large as the competing venue
    # hits wins, matching the explorer's person-vs-namesake rule.
    if person_edges and len(person_edges) >= competing:
        return person_edges
    if venue_edges:
        return venue_edges
    return person_edges

def _public_cluster(c):
    return {"name": c["name"], "aliases": c["aliases"],
            "homonym": c["homonym"], "possible": c["possible"],
            "n": c["n"], "edges": c["edges"]}

def assemble_dossier(q, lin, role=None, era=None, hood=None, es=None):
    """Shape the public search payload.

    Unresolved queries return no lineage. Resolved queries return only
    career-move citations about that entity, and the score counts those.
    era/hood filters travel with the payload plus the facet's coverage
    note, so the UI can disclose what the filter did without a second
    request. es is needed only for the facet-empty existence probe.
    """
    q = (q or "").strip()[:MAX_QUERY_LEN]
    if not q:
        return {"query": "", "resolved": False, "lineage": [], "identity": [], "pedigree": None}
    cl = identity(lin)
    if not resolve_query(q, lin, cl):
        # roadmap 4.4: the era/hood gates act on the retrieval window, so a
        # facet can empty it entirely — resolution then fails HERE, before
        # the facet-aware branch below. Probe the ungated record with the
        # same resolution discipline: if the query names something there,
        # the facet emptied a real dossier — the honest facet-empty state
        # ("is in the record, but none of its cited moves carry era X").
        # If it doesn't resolve unfiltered either, the entity is not in
        # the record and the plain empty state stays honest.
        if (era or hood or role) and es is not None:
            # one shared honest probe: resolution + query-scoped rows +
            # the citation gate. The message claims "none of its cited
            # moves carry era X"; both halves must be proven, not
            # assumed from raw window matches.
            if _cited_moves_exist(es, q):
                out = {"query": q, "resolved": False, "lineage": [], "identity": [],
                       "pedigree": None, "facet_empty": True}
                if role:
                    out["role_filter"] = role
                if era:
                    out["era_filter"] = era
                    out["era_coverage"] = _ERA_COVERAGE
                if hood:
                    out["hood_filter"] = hood
                    out["hood_coverage"] = _HOOD_COVERAGE
                return out
        return {"query": q, "resolved": False, "lineage": [], "identity": [], "pedigree": None}
    scoped = []
    for e in scope_edges(q, lin, cl):
        if not citation_supported(e):
            continue
        row = dict(e)
        row["outlet"] = outlet_tier(e.get("source"), e.get("source_url"))
        row["role_bucket"] = role_bucket(e.get("role"))
        row["supported"] = True
        # display cut only: the gate above judged the full quotation
        row["evidence"] = (row.get("evidence") or "")[:220]
        scoped.append(row)
    if not scoped:
        # Resolution matched something but nothing survived scoping + the
        # citation gate (e.g. "StateBird" resolved via a fuzzy fetch but
        # no fetched edge actually names it). Saying "resolved, no moves"
        # would state a record the index doesn't hold — report unresolved
        # so the reader gets the honest empty-state instead.
        # EXCEPT under an active facet (roadmap 4.4): "Betelnut & era=2010s"
        # emptying means the kitchen exists but its cited dates don't reach
        # that era — the facet's honest-empty state, not the
        # spelling-suggestions one. facet_exists tells the two apart.
        if era or hood or role:
            # the entity resolved in the gated fetch but no row survived
            # scoping + the citation gate. facet_empty only when the same
            # scoping+citation discipline proves cited moves exist
            # ungated AND the deep gated window still holds one: both
            # probes accept nothing on raw term matches alone.
            probe = _cited_moves_exist(es, q) if es else None
            out = {"query": q, "resolved": False, "lineage": [], "identity": [],
                   "pedigree": None,
                   "facet_empty": bool(probe) and bool(
                       _facet_probe(es, q, era=era, hood=hood, role=role))
                   or None if es else None}
            if role:
                out["role_filter"] = role
            if era:
                out["era_filter"] = era
                out["era_coverage"] = _ERA_COVERAGE
            if hood:
                out["hood_filter"] = hood
                out["hood_coverage"] = _HOOD_COVERAGE
            return out
        return {"query": q, "resolved": False, "lineage": [], "identity": [], "pedigree": None}
    cl2 = identity(scoped) if scoped else []
    out = {"query": q, "resolved": True, "lineage": scoped,
           "identity": [_public_cluster(c) for c in cl2],
           "pedigree": pedigree(scoped) if scoped else None}
    if role:
        # the facet note travels with the payload so the UI can say what the
        # filter did without a second request
        out["role_filter"] = role
    if era:
        out["era_filter"] = era
        # dates exist on only 15.6% of edges and not all carry a citable
        # year — an era-filtered dossier must say so or it lies by omission
        out["era_coverage"] = _ERA_COVERAGE
    if hood:
        out["hood_filter"] = hood
        # hood stamps exist for SF venues the city file can place — 43% of
        # edge docs — so the filter discloses partial coverage
        out["hood_coverage"] = _HOOD_COVERAGE
    return out

def _cited_moves_exist(es, q):
    """Does the ungated record hold query-scoped, citation-passing moves?

    The facet-empty message claims "none of its cited moves carry X" — the
    "cited moves" half must be true: rows matched the retrieval window on
    any term (recipe sentences, supplier blurbs) are not the queried
    entity's moves until scoping binds them to the query and the citation
    gate calls a move a move."""
    ungated = lineage(es, q, size=25)
    if not resolve_query(q, ungated, identity(ungated)):
        return None  # not in the record at all
    scoped = scope_edges(q, ungated, identity(ungated))
    return [e for e in scoped if citation_supported(e)] or None


def _facet_probe(es, q, era=None, hood=None, role=None):
    """Did a real dossier exist under these facet gates?

    Runs after _cited_moves_exist proved the entity HAS cited moves
    unfiltered. A size=0 window collects NOTHING for post_filter to gate
    (the RRF window is the only pool post_filter sees), so the probe needs
    a real window. Deep one: ES keeps scanning past `size` until the
    window fills with post_filter survivors, so a 300-deep window is an
    honest "any such edge exists" at corpus scale. The discriminator is
    RESOLUTION, not citation: "none of its cited moves carry era X" is
    true when the gated fetch still names the entity (the dossier the
    chips claim to filter) even though its surviving rows fail the
    citation gate — that is the facet emptying a real record, not
    nothing-in-the-record."""
    hits = find_edges(es, q, size=300, role=role, era=era, hood=hood)
    edges = [_probe_edge(h) for h in hits]
    return bool(resolve_query(q, edges, identity(edges)))

def _probe_edge(h):
    """Raw ES hit -> edge dict shaped the way lineage() shapes them, so
    scope_edges/identity/citation_supported see the same fields."""
    s = h["_source"]
    return {
        "person": s.get("person"), "from_venue": s.get("from_venue"),
        "to_venue": s.get("to_venue"), "role": s.get("role"),
        "date": s.get("date"), "confidence": s.get("confidence"),
        "source": s.get("source"), "action": s.get("action"),
        "evidence": s.get("evidence") or "", "source_url": s.get("source_url"),
        "score": h.get("_score", 0),
    }

def pedigree(edges):
    """Weighted credibility of the edges passed in (already entity-scoped).

    Authority is Chronicle-weighted (55pts), article corroboration (25pts),
    and depth (20pts). Unknown hosts are tier `other` at weight 3.
    """
    if not edges:
        return None
    tiers = {"sfchronicle": 0, "sfgate": 0, "eater": 0}
    total = 0
    urls = set()
    other = 0
    for e in edges:
        t = e.get("outlet") or outlet_tier(e.get("source"), e.get("source_url"))
        if t not in TIER_WEIGHT:
            t = "other"
        if t == "other":
            other += 1
            total += 3  # unranked outlets: lighter than Eater, never borrow its weight
        else:
            tiers[t] += 1
            total += TIER_WEIGHT[t]
        if e.get("source_url"):
            urls.add(e["source_url"])
    authority = total / (len(edges) * TIER_WEIGHT["sfchronicle"])
    corroboration = min(1.0, max(0, len(urls) - 1) / 4)
    depth = min(1.0, len(edges) / 12)
    score = round(55 * authority + 25 * corroboration + 20 * depth)
    tiers["other"] = other
    return {"score": min(100, score),
            "moves": len(edges), "sources": len(urls), "tiers": tiers}

# ── ES query layer ──
def lineage(es, query, size=25, role=None, era=None, hood=None):
    """All edges matching a venue or person, split into inbound/outbound by the UI.

    evidence is stored in full: citation_supported() must see the whole
    quotation (a move stated past the display cutoff still counts). The
    public payload is shortened for display in assemble_dossier().
    role/era/hood: optional facet filters (roadmap 4.3/4.4), applied inside
    the ES query as post_filter gates.
    """
    hits = find_edges(es, query, size=size, role=role, era=era, hood=hood)
    edges = []
    for h in hits:
        s = h["_source"]
        edges.append({
            "person": s.get("person"),
            "from_venue": s.get("from_venue"),
            "to_venue": s.get("to_venue"),
            "role": s.get("role"),
            "date": s.get("date"),
            "confidence": s.get("confidence"),
            "source": s.get("source"),
            "action": s.get("action"),
            "evidence": s.get("evidence") or "",
            "source_url": s.get("source_url"),
            "source_image": s.get("source_image"),
            # Timeline fields. era_bucket places a move in time where the
            # article yielded a citable year; mentor marks the rare edges that
            # name who someone trained under; published_at is when the ARTICLE
            # ran, never when the move happened. A timeline must not conflate
            # the three, so all three travel.
            "era_bucket": s.get("era_bucket"),
            # The citable year itself. era_bucket orders by decade, which is
            # all a facet filter needs, but a timeline has to place two moves
            # from the SAME decade relative to each other and a bucket cannot.
            "year": s.get("year"),
            "mentor": s.get("mentor"),
            "published_at": s.get("published_at"),
            "score": h.get("_score", 0),
        })
    return edges

def _edge_key(e):
    return (e.get("person"), e.get("from_venue"), e.get("to_venue"),
            e.get("role"), e.get("action"), e.get("source_url"))

def dedupe(edges):
    seen, out = set(), []
    for e in edges:
        k = _edge_key(e)
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out

def fetch_person_edges(es, names, limit=100):
    """Full edge set for exact person strings — targeted completion when the
    search-ranked slice fragments a chef's record (name variants, possible
    splits). A bridge edge the hybrid ranking missed can reconnect them."""
    body = {"size": limit, "query": {"bool": {"filter": [
        {"terms": {"person.keyword": names}}]}},
        "_source": ["person", "from_venue", "to_venue", "role", "date",
                    "confidence", "source", "action", "evidence", "source_url",
                    "source_image", "role_bucket", "era_bucket", "venue_hoods",
                    "year",
                    # mentor + published_at travel too: completion edges land in
                    # the same timeline, and omitting mentor drops the "under …"
                    # line from a row that has one stored
                    "mentor", "published_at"]}
    r = es.search(index=INDEX, body=body)
    out = []
    for h in r["hits"]["hits"]:
        s = h["_source"]
        out.append({
            "person": s.get("person"), "from_venue": s.get("from_venue"),
            "to_venue": s.get("to_venue"), "role": s.get("role"),
            "date": s.get("date"), "confidence": s.get("confidence"),
            "source": s.get("source"), "action": s.get("action"),
            "evidence": s.get("evidence") or "",
            "source_url": s.get("source_url"),
            "source_image": s.get("source_image"), "score": 0,
            # facet stamps travel so the merge site can gate completion
            # rows by the same facets the ranked window used
            "role_bucket": s.get("role_bucket"),
            "era_bucket": s.get("era_bucket"),
            # year travels with the facet stamps: a completion row merged next
            # to a ranked row must partition on the same time key, or the same
            # move splits into an e2010s row and a y2013 row.
            "year": s.get("year"),
            "venue_hoods": s.get("venue_hoods") or [],
            "mentor": s.get("mentor"),
            "published_at": s.get("published_at"),
        })
    return out

def _suggest_top(es, prefix, size):
    """Fallback: top venue buckets, filtered in process. No hybrid search."""
    body = {
        "size": 0,
        "aggs": {
            "venues": {"terms": {"field": "to_venue.keyword", "size": 40}},
            "from_venues": {"terms": {"field": "from_venue.keyword", "size": 40}},
        },
    }
    r = es.search(index=INDEX, body=body)
    names = set()
    for b in r["aggregations"]["venues"]["buckets"] + r["aggregations"]["from_venues"]["buckets"]:
        name = b["key"]
        if name and prefix.lower() in name.lower():
            names.add(name)
    return sorted(names)[:size]

def _suggest_safe(prefix):
    """Query for the wildcard matcher: keep every letter (Unicode included —
    "Jardinière" must not lose its è) plus digits/space/&/', and drop the
    characters that are special inside an ES wildcard expression."""
    s = re.sub(r"[*?\[\]\\]", " ", prefix)
    return re.sub(r"[^\w &'.’\-]", "", s, flags=re.UNICODE)[:40]

def suggest(es, prefix, size=7):
    """Venue name suggestions. Wildcard on the keyword field, not a dossier search."""
    prefix = (prefix or "").strip()
    if len(prefix) < 2:
        return []
    safe = _suggest_safe(prefix)
    if len(safe) < 2:
        return _suggest_top(es, prefix, size)
    pattern = "*" + safe + "*"
    try:
        names = set()
        for field in ("to_venue.keyword", "from_venue.keyword"):
            body = {
                "size": 0,
                "query": {"wildcard": {field: {"value": pattern, "case_insensitive": True}}},
                "aggs": {"names": {"terms": {"field": field, "size": max(size, 20)}}},
            }
            r = es.search(index=INDEX, body=body)
            for b in r["aggregations"]["names"]["buckets"]:
                if b["key"]:
                    names.add(b["key"])
        return sorted(names)[:size]
    except Exception:
        return _suggest_top(es, prefix, size)

def _distinct_values(es, field, page=10000):
    """Every distinct value of a keyword field, via composite aggregation.

    `terms` caps at the requested size, which silently truncates a corpus this
    big (the old stats() asked for 500 per field and reported 799 kitchens
    against 4,000+ real ones). composite pages through all of them.

    page=10000 is ES's default composite max_buckets, so a corpus this size
    resolves in ONE round-trip per field instead of 4-5. The corpus would have
    to pass 10k distinct values before this needed a second page."""
    out, after = set(), None
    while True:
        comp = {"size": page, "sources": [{"v": {"terms": {"field": field}}}]}
        if after:
            comp["after"] = after
        agg = es.search(index=INDEX, body={
            "size": 0, "aggs": {"v": {"composite": comp}}})["aggregations"]["v"]
        buckets = agg["buckets"]
        out |= {b["key"]["v"] for b in buckets if b["key"]["v"]}
        after = agg.get("after_key")
        if not buckets or not after:
            return out

# Corpus-size cache. /api/stats is fetched on every landing and explorer page
# load, and counting distinct venue names costs several aggregation round-trips
# even at page=10000. The corpus grows in periodic scrape runs, not per
# request, so a warm Vercel instance can answer every visitor for a few
# minutes from one computation. Keyed by nothing: the corpus is one global
# index. A cold instance simply recomputes.
_STATS_TTL = 300.0  # seconds
_STATS_CACHE = {"at": 0.0, "value": None}


def stats(es):
    """Top-line corpus stats for the masthead counter.

    venues counts distinct venue IDENTITIES, not distinct spellings. Each name
    is filtered by the same junk/chain rule the map uses, then resolved with
    venue_key() — the shared identity path that folds formatting (accents,
    parens, a leading "The") and applies the owner's rulings from
    ui/venue_aliases.json. So "Michael Mina" and "Restaurant Michael Mina" are
    one kitchen, as are "The French Laundry" and "French Laundry".

    Before this, the count used norm_venue, which resolved aliases only by
    accident of string similarity; the index already stored from_venue_key /
    to_venue_key but no reader consumed them, so the ruling changed nothing
    that was displayed.

    Result is memoized for _STATS_TTL: the count is identical on every call
    until the next scrape run, and visitors were otherwise paying for the same
    full scan each page load.
    """
    now = time.time()
    cached = _STATS_CACHE["value"]
    if cached is not None and now - _STATS_CACHE["at"] < _STATS_TTL:
        return cached

    venues_raw = _distinct_values(es, "from_venue.keyword") \
        | _distinct_values(es, "to_venue.keyword")
    venues = {venue_key(v) for v in venues_raw
              if v and not _is_junk_venue(v) and venue_key(v)}
    agg = es.search(index=INDEX, body={"size": 0, "aggs": {
        "people": {"cardinality": {"field": "person.keyword",
                                   "precision_threshold": 40000}},
        "sources": {"cardinality": {"field": "source_url.keyword",
                                    "precision_threshold": 40000}},
    }})["aggregations"]
    value = {"edges": es.count(index=INDEX)["count"],
             "people": agg["people"]["value"],
             "venues": len(venues),
             "sources": agg["sources"]["value"]}
    _STATS_CACHE["at"], _STATS_CACHE["value"] = now, value
    return value

# Non-restaurant names the extraction produced ("Google kitchen", "TBD") and
# chains. Shared by venues_geo (map dots) and stats (kitchen count) so the
# headline number and the map draw from the same definition of a kitchen.
_JUNK_WORDS = ("tbd", "to be determined", "facebook", "walgreen", "google",
               "salesforce", "amazon", "apple inc", "airbnb", "uber",
               "doordash", "lyft", "bon appetit", "proper food", "mixt",
               "test ", "unknown", "null", "none")

# Whole-name group descriptors: a restaurant group, not a kitchen.
_GROUP_NAMES = ("plumpjack empire", "plumpjack group")
_CHAIN_NAMES = ("mcdonald", "starbucks", "burger king", "jack in the box",
                "kentucky fried", "little caesars", "popeyes", "chipotle",
                "subway", "jamba juice", "peet", "philz", "phil'z", "taco bell",
                "wendy", "dunkin", "in n out", "mrs field", "cold stone",
                "dairy queen", "potbelly", "panera", "noah")


def _tokens(s):
    """Lowercase word tokens, punctuation folded to spaces."""
    return "".join(c if c.isalnum() or c.isspace() else " "
                   for c in (s or "").lower()).split()


def _is_junk_venue(name):
    """True when a venue name is a non-kitchen artefact, not a restaurant.

    Junk terms match as WHOLE TOKEN SEQUENCES, never substrings. Substring
    matching silently dropped real SF restaurants whose names merely contain
    a chain fragment: "Schubert's Bakery" and "Petite Auberge" both contain
    "uber" and were excluded from the corpus count.

    Multi-word terms match as contiguous phrases ("burger king" inside
    "Burger King Market St"), so a chain with a branch suffix still counts
    while a name that merely contains the letters does not.
    """
    toks = _tokens(name)
    if not toks:
        return True
    joined = " " + " ".join(toks) + " "
    # A group descriptor matches only when it IS the whole name.
    if " ".join(toks) in _GROUP_NAMES:
        return True
    for term in _JUNK_WORDS + _CHAIN_NAMES:
        t = _tokens(term)
        if t and (" " + " ".join(t) + " ") in joined:
            return True
    return False

def venues_geo(es=None):
    """Venues for the map: the full SF permitted-food universe (ui/city_venues.json,
    written by src/pull_city.py) merged with the curated geocode cache (ui/venues_geo.json).

    Quiet-dot curation: only eateries keep a dot. Chains, corporate cafeterias,
    tobacco shops, pushcarts, schools and other permitted-but-not-a-kitchen
    rows are dropped so the universe layer reads as "San Francisco restaurants".
    Lineaged/michelin rows always survive."""
    KEEP_TYPES = ("H24", "H25", "H26", "H28", "H29", "H86", "H87", "H88")

    def keep_type(t):
        t = t or ""
        return any(t == k or t.startswith(k + " ") or t.startswith(k + " -")
                   or t.startswith(k + "R") for k in KEEP_TYPES)

    def keep(v):
        if v.get("lineaged") or v.get("michelin"):
            return True
        return keep_type(v.get("permit_type")) and not _is_junk_venue(v.get("name"))

    venues = []
    city = data_path("city_venues.json")
    if os.path.exists(city):
        with open(city) as f:
            venues = [v for v in json.load(f)["venues"] if keep(v)]
    curated = data_path("venues_geo.json")
    if os.path.exists(curated):
        with open(curated) as f:
            by_name = {v["name"].lower(): v for v in venues}
            for v in json.load(f)["venues"]:
                hit = by_name.get(v["name"].lower())
                if hit is None:
                    # curated pin not in the city list (closed venues: Betelnut, Gitane, Stars…)
                    # every curated pin came from the lineage graph, so it is lineaged by construction
                    v.setdefault("lineaged", True)
                    venues.append(v)
                else:
                    if v.get("website"): hit["website"] = v["website"]  # curated metadata wins
    return venues


# ── relevance gate: did the query actually name a chef or kitchen we cite? ──
# Hybrid search ranks by relevance, not resolution — a nonsense query still
# returns its 25 nearest records. The dossier UI needs to know whether any
# cluster genuinely IS the query, not merely nearby it.
def resolve_query(q, lin, cl):
    """Did the query actually name a cited chef or kitchen?"""
    ql = q.lower().strip()
    if not ql:
        return False
    for c in cl:
        for n in [c["name"], *(c.get("aliases") or [])]:
            if n.lower() == ql and not _is_collective(n):
                return True
            # punctuation-loose name match ("Mister Jius" → "Mister Jiu's")
            if _same_loose(n, ql) and not _is_collective(n):
                return True
    for e in lin:
        for k in ("from_venue", "to_venue"):
            v = e.get(k)
            if v and v.lower() == ql:
                return True
            if _same_loose(v, ql):
                return True
    # prefix tolerance for partial kitchen names ("Finn Town" → "Finn Town
    # Taproom"). Both directions gated on len>=4 so "nopalera" cannot absorb
    # "Nopa" (a different venue) — the query must extend the cited name.
    for e in lin:
        for k in ("from_venue", "to_venue"):
            v = e.get(k)
            if v and len(ql) >= 4:
                vl = v.lower()
                if len(vl) >= 4 and (vl.startswith(ql) or ql.startswith(vl)):
                    return True
    return False


# ── HTTP dispatch shared by both runtimes ──
def _json_response(status, obj, extra_headers=None):
    headers = {"Content-Type": "application/json"}
    headers.update(extra_headers or {})
    return status, headers, json.dumps(obj).encode()


def _too_many():
    return _json_response(429, {"error": "too many requests"}, {"Retry-After": "60"})


def map_js():
    """map.js with the Mapbox token injected, so the token lives only in env
    and the response body, never in a committed file."""
    try:
        with open(data_path("map.js")) as f:
            js = f.read()
    except OSError:
        return 404, {"Content-Type": "text/plain"}, b"not found"
    inject = "window.MAPBOX_TOKEN = %s;\n" % json.dumps(os.environ.get("MAPBOX_TOKEN", ""))
    return 200, {"Content-Type": "application/javascript; charset=utf-8",
                 "Cache-Control": "public, max-age=300"}, (inject + js).encode()


def _search(es, q1):
    q = (q1("q") or "").strip()[:MAX_QUERY_LEN]
    size = clamp_size(q1("size"))
    # role/era/hood facets filter on the index-time stamps; unknown values are
    # ignored, never a 500
    role = (q1("role") or "").strip()
    role = role if role in _ROLE_BUCKETS else None
    era = (q1("era") or "").strip()
    era = era if era in _ERA_BUCKETS else None
    hood = (q1("hood") or "").strip()
    hood = hood if hood in _HOOD_VOCAB else None
    if not q:
        return {"query": "", "resolved": False, "lineage": [], "identity": [], "pedigree": None}
    lin = lineage(es, q, size=size, role=role, era=era, hood=hood)
    cl = identity(lin)
    # targeted completion: fragmented records (name variants, same-chef
    # candidates) get their full edge set pulled by exact name, then the whole
    # set is re-clustered, so a bridge the hybrid ranking missed can reconnect
    # components honestly (shared venue or shared article).
    need = sorted({n for c in cl if c["homonym"] or c["possible"]
                   for n in [c["name"], *c["aliases"]]})
    if need:
        have = {_edge_key(e) for e in lin}
        extra = [e for e in fetch_person_edges(es, need) if _edge_key(e) not in have]
        if extra:
            # facet gates apply to completion edges too: a row fetched ungated
            # must not surface in a dossier the chips claim is filtered.
            extra = [e for e in extra
                     if (not role or e.get("role_bucket") == role)
                     and (not era or e.get("era_bucket") == era)
                     and (not hood or hood in (e.get("venue_hoods") or []))]
            lin = dedupe(lin + extra)
    return assemble_dossier(q, lin, role=role, era=era, hood=hood, es=es)


def _tip(es, ip, body_bytes):
    """Reader-submitted correction or source tip -> tips inbox.

    Queue, not corpus: nothing here enters the lineage index without the
    citation gate and a human triage pass (scripts/review_tips.py)."""
    if not body_bytes or len(body_bytes) > 4096:
        return _json_response(400, {"error": "invalid body"})
    try:
        payload = json.loads(body_bytes.decode("utf-8", "replace"))
    except Exception:
        return _json_response(400, {"error": "invalid body"})
    ok, doc_or_err = accept_tip(payload, ip)
    if not ok:
        return _json_response(400, {"error": doc_or_err})
    if doc_or_err is not None:  # None = honeypot: accepted silently, never stored
        ensure_tips_index(es)
        es.index(index=TIPS_INDEX, document=doc_or_err, refresh=False)
    return _json_response(200, {"ok": True})


# endpoint -> (rate-limit bucket, limit, window seconds)
_LIMITS = {"search": ("search", 30, 60), "suggest": ("suggest", 90, 60), "tip": ("tips", 5, 3600)}


def dispatch(path, query_string="", ip="", body_bytes=None, client=make_client):
    """Handle one /api/* request. Returns (status, headers, body_bytes).

    `client` is a zero-argument callable returning an Elasticsearch client, so
    each runtime decides how clients are created and cached."""
    endpoint = path.rstrip("/").rsplit("/", 1)[-1]
    qs = parse_qs(query_string or "")

    def q1(k):
        v = qs.get(k)
        return v[0] if v else None

    ip = ip or "unknown"
    if endpoint in _LIMITS:
        bucket, limit, window = _LIMITS[endpoint]
        if not allow_request(bucket, ip, limit, window):
            return _too_many()
    if endpoint == "map.js":
        return map_js()
    try:
        if endpoint == "venues":
            return _json_response(200, {"venues": venues_geo()})
        es = client()
        if endpoint == "search":
            body = _search(es, q1)
        elif endpoint == "suggest":
            q = (q1("q") or "").strip()[:MAX_QUERY_LEN]
            body = {"query": q, "suggestions": suggest(es, q) if q else []}
        elif endpoint == "stats":
            body = stats(es)
        elif endpoint == "method":
            body = method(es)
        elif endpoint == "tip":
            return _tip(es, ip, body_bytes)
        else:
            return _json_response(404, {"error": "unknown endpoint"})
        return _json_response(200, body)
    except Exception:
        traceback.print_exc()  # log the real cause; the response stays generic
        # exception text can leak index names / endpoints
        return _json_response(500, {"error": "search temporarily unavailable"})
