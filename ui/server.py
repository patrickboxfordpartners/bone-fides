"""Bone Fides demo UI: static page + JSON query API against the lineage index."""
import os, sys, json, re, time, traceback, urllib.parse, datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src.cli import load_env
load_env(os.path.join(BASE, ".env"))

from src.es import make_client, find_edges, INDEX, TIPS_INDEX, ensure_tips_index, build_tip_doc

ROOT = os.path.dirname(os.path.abspath(__file__))

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
            "score": h.get("_score", 0),
        })
    return edges

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
    from src.es import find_edges as _fe
    hits = _fe(es, q, size=300, role=role, era=era, hood=hood)
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

# Pedigree: source-tier weighting (the triangulation story). The Chronicle is
# the paper of record — a verified personnel change weighs most; SFGate is the
# same newsroom, lighter; Eater moves fastest but is the softest citation.
TIER_WEIGHT = {"sfchronicle": 12, "sfgate": 8, "eater": 6}

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

def norm_venue(v):
    """Normalized venue key for overlap matching only (never displayed):
    drop parenthetical annotations (Saison (2124 Folsom St.) == Saison),
    trailing possessives (Chez TJ's == Chez TJ), unicode-fold accents
    (Jardinière == Jardiniere), straighten apostrophes, strip punctuation,
    drop stop words (The Commissary == Commissary)."""
    import unicodedata as _ud
    v = re.sub(r'\([^)]*\)', ' ', v)                      # (Folsom St. location)
    v = _ud.normalize("NFD", v)
    v = "".join(ch for ch in v if not _ud.combining(ch))
    v = v.replace(chr(8217), "'").replace(chr(8216), "'")
    v = re.sub(r"['’]s?\b", '', v)                        # possessive TJ's -> TJ
    v = re.sub(r'[^a-z0-9\s]', '', v.lower())
    toks = [t for t in v.split() if t not in ("the", "a", "an", "of", "at", "in", "on")]
    return ' '.join(toks)

# One-token names that are not a restaurant. "bar" must not glue "bar tartine".
_GENERIC_VENUE = {"bar", "cafe", "kitchen", "grill", "house", "restaurant", "room", "club", "san", "sf", "food", "wine", "bakery"}

def _venue_touch(va, vb):
    """Exact match, or the shorter name is a leading-token prefix of the longer
    (Betelnut ⊂ Betelnut Pejiu Wu). A single generic token does not match."""
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
    """Set of normalized venue keys an edge set touches (from_venue + to_venue)."""
    v = set()
    for e in edges:
        for k in ("from_venue", "to_venue"):
            if e.get(k):
                v.add(norm_venue(e[k]))
    return v

def edge_urls(edges):
    """Set of source URLs an edge set cites (same article = same subject)."""
    return {e["source_url"] for e in edges if e.get("source_url")}

def _keysplit(key):
    """(first, last) tokens of a normalized person key, or (None, None)."""
    t = key.split()
    return (t[0], t[-1]) if len(t) >= 2 else (None, None)

# Given-name nicknames only. A raw prefix would merge Dan/Danielle and
# Chris/Christina. Each value is the one canonical long form we accept.
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

# Career-move language. A recipe sentence that merely names a title
# ("combines it with butter") is not a promotion. Plain career facts the
# extraction prompt asks for — "worked at Betelnut", "worked under Thomas
# Keller", "trained at French Laundry" — are accepted too: they are the
# mentor/stint sentences that build a lineage.
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

_ROLE_CHEF = {"chef", "chefs", "cook", "cooks", "culinary", "cuisine", "kitchen", "pizzaiolo", "commis"}
_ROLE_EXEC = {"executive", "exec", "corporate"}
_ROLE_PASTRY = {"pastry", "baker", "bakery", "baking", "chocolatier", "dessert", "chocolate"}
_ROLE_SOUS = {"sous"}
_ROLE_OWNER = {"owner", "owners", "founder", "founders", "founding", "proprietor", "proprietors",
               "restaurateur", "restaurateurs", "partner", "partners", "operator", "operators"}
_ROLE_BAR = {"bartender", "barman", "barback", "bar"}
# the bucket vocabulary the &role= facet accepts (src.roles.BUCKETS twin)
_ROLE_BUCKETS = {"chef", "executive chef", "pastry", "sous", "owner", "bartender", "other"}
# era + hood vocabularies (roadmap 4.4, src.eras.ERA_BUCKETS and
# src.hoods.hood_vocabulary twins). Hoods mirror the city file's
# analysis_neighborhood labels — the exact list is locked by test.
_ERA_BUCKETS = {"pre-1990", "1990s", "2000s", "2010s", "2020s"}
# coverage notes travel with every facet-filtered payload (the corpus's
# dates and SF-placeable venues are partial; the filter must say so)
_ERA_COVERAGE = "dates on 15% of cited moves"
_HOOD_COVERAGE = "neighborhoods on 43% of cited moves"
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

def role_bucket(role):
    """Raw role text -> dossier filter bucket. Token-based synonym fold, same
    discipline as norm_venue: case-fold and split on separators, never guess
    from substrings (a "bar manager" is not a "bar" and a "chocolate martini"
    must not make anyone a pastry chef). Domain beats seniority — an
    "executive pastry chef" is pastry, an "executive sous chef" is sous;
    ownership reads as chef first ("chef-owner" cooks), chef-first when both
    appear. Anything else stays other (managers, sommeliers, junk rows)."""
    s = re.sub(r"[^a-z0-9&\s'-]", " ", (role or "").lower())
    toks = set(re.split(r"[\s/&,'\-]+", s)) - {""}
    if not toks:
        return "other"
    if toks & _ROLE_SOUS:
        return "sous"
    if toks & _ROLE_PASTRY:
        return "pastry"
    if (toks & _ROLE_EXEC) and (toks & _ROLE_CHEF):
        return "executive chef"
    if toks & _ROLE_CHEF:
        return "chef"
    if toks & _ROLE_BAR:
        return "bartender"
    if toks & _ROLE_OWNER:
        return "owner"
    return "other"

def _loose(s):
    """Punctuation-loose comparison key: lowercase letters and digits only.
    "Mister Jiu's" and "Mister Jius" are the same kitchen to a reader who
    skipped the apostrophe; "flour+water" and "flour water" likewise."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

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

# Non-restaurant names the extraction produced ("Google kitchen", "TBD") and
# chains. Shared by venues_geo (map dots) and stats (kitchen count) so the
# headline number and the map draw from the same definition of a kitchen.
_JUNK_WORDS = ("tbd", "to be determined", "facebook", "walgreen", "google",
               "salesforce", "amazon", "apple inc", "airbnb", "uber",
               "doordash", "lyft", "bon appetit", "proper food", "mixt",
               "test ", "unknown", "null", "none")
_CHAIN_NAMES = ("mcdonald", "starbucks", "burger king", "jack in the box",
                "kentucky fried", "little caesars", "popeyes", "chipotle",
                "subway", "jamba juice", "peet", "philz", "phil'z", "taco bell",
                "wendy", "dunkin", "in n out", "mrs field", "cold stone",
                "dairy queen", "potbelly", "panera", "noah")

def _is_junk_venue(name):
    n = (name or "").lower()
    return (not n.strip()) or any(w in n for w in _JUNK_WORDS) \
        or any(c in n for c in _CHAIN_NAMES)

def venues_geo(es):
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
    city = os.path.join(ROOT, "city_venues.json")
    if os.path.exists(city):
        with open(city) as f:
            venues = [v for v in json.load(f)["venues"] if keep(v)]
    curated = os.path.join(ROOT, "venues_geo.json")
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
                    "source_image", "role_bucket", "era_bucket", "venue_hoods"]}
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
            "venue_hoods": s.get("venue_hoods") or [],
        })
    return out

def _distinct_values(es, field, page=1000):
    """Every distinct value of a keyword field, via composite aggregation.

    `terms` caps at the requested size, which silently truncates a corpus this
    big (the old stats() asked for 500 per field and reported 799 kitchens
    against 4,100+ real ones). composite pages through all of them."""
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

def stats(es):
    """Top-line corpus stats for the masthead counter.

    venues is the count of distinct KITCHENS — venue names folded with the
    same norm_venue the dossier uses ("Tartine" / "Tartine Bakery" are one
    kitchen) and filtered with the same junk/chain rule the map uses. It is
    deliberately not a raw name count: that number would overstate the
    corpus by counting typo variants and chains as separate restaurants.
    """
    venues_raw = _distinct_values(es, "from_venue.keyword") \
        | _distinct_values(es, "to_venue.keyword")
    venues = {norm_venue(v) for v in venues_raw
              if v and not _is_junk_venue(v) and norm_venue(v)}
    agg = es.search(index=INDEX, body={"size": 0, "aggs": {
        "people": {"cardinality": {"field": "person.keyword",
                                   "precision_threshold": 40000}},
        "sources": {"cardinality": {"field": "source_url.keyword",
                                    "precision_threshold": 40000}},
    }})["aggregations"]
    return {"edges": es.count(index=INDEX)["count"],
            "people": agg["people"]["value"],
            "venues": len(venues),
            "sources": agg["sources"]["value"]}

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

# Best-effort per-instance throttle. Warm Vercel isolates share this dict;
# a cold start starts empty. Enough to blunt a tight loop without a datastore.
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

def resolve_query(q, lin, cl):
    """Did the query actually name a cited chef or kitchen? Same logic as
    vercel-app/api/search.py — keep the two in sync."""
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

class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        es = self.server.es
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/api/tip"):
            self._safe(lambda: self._tip(es))
        else:
            self.send_error(404)

    def do_GET(self):
        es = self.server.es
        path = urllib.parse.urlsplit(self.path).path  # ignore query string for routing
        if path.startswith("/api/search"):
            self._safe(lambda: self._search(es))
        elif path.startswith("/api/suggest"):
            self._safe(lambda: self._suggest(es))
        elif path.startswith("/api/venues"):
            self._safe(lambda: self._json({"venues": venues_geo(es)}))
        elif path.startswith("/api/map.js"):
            self._serve_mapjs()
        elif path.startswith("/api/stats"):
            self._safe(lambda: self._json(stats(es)))
        elif path in ("/", "/landing", "/landing.html"):
            # "/" serves the landing page — same as the Vercel rewrite.
            self._serve_landing()
        elif path in ("/explorer", "/explorer/", "/explorer.html", "/explorer/index.html"):
            self._serve_explorer()
        else:
            super().do_GET()

    def _client_ip(self):
        fwd = self.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
        return self.client_address[0] if self.client_address else ""

    def _search(self, es):
        if not allow_request("search", self._client_ip() or "unknown", 30, 60):
            self._json({"error": "too many requests"}, status=429)
            return
        m = re.search(r"q=([^&]*)", self.path)
        # unquote_plus, not unquote: URLSearchParams sends spaces in q as
        # '+', and a partial query ("Finn Town") must match ("Finn Town
        # Taproom") the way the vercel twin's parse_qs decoding does
        q = urllib.parse.unquote_plus(m.group(1)) if m else ""
        q = q.strip()[:MAX_QUERY_LEN]
        ms = re.search(r"size=(\d+)", self.path)
        size = clamp_size(ms.group(1)) if ms else 25
        # role facet (roadmap 4.3): &role=<bucket> filters the ES query on the
        # index-time stamp; unknown values are ignored, never 500
        mr = re.search(r"role=([^&]*)", self.path)
        role = urllib.parse.unquote_plus(mr.group(1)).strip() if mr else ""
        role = role if role in _ROLE_BUCKETS else None
        # era + hood facets (roadmap 4.4): same discipline, unknown values
        # ignored (hood labels carry slashes — percent-decode first)
        me = re.search(r"era=([^&]*)", self.path)
        era = urllib.parse.unquote_plus(me.group(1)).strip() if me else ""
        era = era if era in _ERA_BUCKETS else None
        mh = re.search(r"hood=([^&]*)", self.path)
        hood = urllib.parse.unquote_plus(mh.group(1)).strip() if mh else ""
        hood = hood if hood in _HOOD_VOCAB else None
        lin = lineage(es, q, size=size, role=role, era=era, hood=hood) if q else []
        cl = identity(lin) if q else []
        # targeted completion: fragmented records (name variants, same-chef
        # candidates) get their full edge set pulled by exact name, then the
        # whole set is re-clustered — a bridge the hybrid ranking missed can
        # reconnect components honestly (shared venue or shared article).
        need = sorted({n for c in cl if c["homonym"] or c["possible"]
                       for n in [c["name"], *c["aliases"]]})
        if need:
            have = {_edge_key(e) for e in lin}
            extra = [e for e in fetch_person_edges(es, need) if _edge_key(e) not in have]
            if extra:
                # facet gates apply to completion edges too: a row fetched
                # ungated must not surface in a dossier the chips claim is
                # role/era/hood-filtered. Same set-membership stamps the
                # ranked window was gated on.
                extra = [e for e in extra
                         if (not role or e.get("role_bucket") == role)
                         and (not era or e.get("era_bucket") == era)
                         and (not hood or hood in (e.get("venue_hoods") or []))]
                lin = dedupe(lin + extra)
        self._json(assemble_dossier(q, lin, role=role, era=era, hood=hood, es=es) if q else
                   {"query": "", "resolved": False, "lineage": [], "identity": [], "pedigree": None})

    def _suggest(self, es):
        if not allow_request("suggest", self._client_ip() or "unknown", 90, 60):
            self._json({"error": "too many requests"}, status=429)
            return
        m = re.search(r"q=([^&]*)", self.path)
        # unquote_plus: same + encoding as _search above
        q = urllib.parse.unquote_plus(m.group(1)) if m else ""
        q = q.strip()[:MAX_QUERY_LEN]
        self._json({"query": q, "suggestions": suggest(es, q) if q else []})

    def _tip(self, es):
        """Reader-submitted correction or source tip -> tips inbox.

        Queue, not corpus: nothing here enters the lineage index without the
        citation gate and a human triage pass (src/review_tips.py)."""
        if not allow_request("tips", self._client_ip() or "unknown", 5, 3600):
            self._json({"error": "too many requests"}, status=429)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 4096:
            self._json({"error": "invalid body"}, status=400)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except Exception:
            self._json({"error": "invalid body"}, status=400)
            return
        ok, doc_or_err = accept_tip(payload, self._client_ip() or "unknown")
        if not ok:
            self._json({"error": doc_or_err}, status=400)
            return
        if doc_or_err is None:  # honeypot: accepted silently, never stored
            self._json({"ok": True})
            return
        ensure_tips_index(es)
        es.index(index=TIPS_INDEX, document=doc_or_err, refresh=False)
        self._json({"ok": True})

    def _safe(self, fn):
        try:
            fn()
        except Exception:
            traceback.print_exc()  # log the real cause; response stays generic
            # generic error surface: exception text can leak index names/endpoints
            try:
                self._json({"error": "search temporarily unavailable"}, status=500)
            except Exception:
                pass

    def _serve_explorer(self):
        """Serve explorer.html with the Mapbox token injected as window.MAPBOX_TOKEN."""
        try:
            with open(os.path.join(ROOT, "explorer.html")) as f:
                html = f.read()
        except OSError:
            self.send_error(404)
            return
        inject = "<script>window.MAPBOX_TOKEN = %s;</script>" % json.dumps(os.environ.get("MAPBOX_TOKEN", ""))
        html = html.replace("</head>", inject + "</head>", 1)
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_mapjs(self):
        """map.js with the Mapbox token injected — local twin of the Vercel
        /api/map.js handler, so both front-ends load the script identically."""
        try:
            with open(os.path.join(ROOT, "map.js")) as f:
                js = f.read()
        except OSError:
            self.send_error(404)
            return
        inject = "window.MAPBOX_TOKEN = %s;\n" % json.dumps(os.environ.get("MAPBOX_TOKEN", ""))
        body = (inject + js).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        # Vercel's twin (vercel-app/api/search.py) sends this; match it
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_landing(self):
        """Serve landing.html verbatim (static page, no token injection)."""
        try:
            with open(os.path.join(ROOT, "landing.html")) as f:
                body = f.read().encode()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # keep demo console clean

def main(port=8017):
    os.chdir(ROOT)  # static files resolve relative to ui/, regardless of launch dir
    es = make_client()
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.es = es
    server.serve_forever()

if __name__ == "__main__":
    main()
