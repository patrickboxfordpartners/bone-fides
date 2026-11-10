"""Vercel Python function: /api/* handlers, the live ES layer of Bone Fides.

Same query logic as ui/server.py (lineage + identity clustering + pedigree)
but stateless per-request: ES client is cached across warm invocations.
Credentials come from env vars (ELASTIC_ENDPOINT, ELASTIC_API_KEY,
MAPBOX_TOKEN) — never printed, never committed.
"""
import os, sys, json, re, time, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Data files are bundled next to this file via includeFiles.
_HERE = os.path.dirname(os.path.abspath(__file__))

INDEX = "bone-fides-edges"

MAX_QUERY_LEN = 120  # abuse cap: queries are names, not free-text essays
MAX_RESULT_SIZE = 40  # a dossier, not a corpus dump

TIP_TYPES = ("wrong person", "wrong venue", "wrong detail",
             "add a move", "add a source")
MAX_TIP_NOTE = 500
MAX_TIP_URL = 300

def accept_tip(payload, ip):
    """Validate a reader-submitted correction/tip into a storable doc.
    Same logic as ui/server.py — keep the two in sync. doc_or_error is
    None when the tip is accepted but must not be stored (honeypot)."""
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

TIPS_INDEX = "bone-fides-tips"
TIPS_SETTINGS = {
    "mappings": {
        "properties": {
            "query": {"type": "keyword"},
            "context": {"type": "keyword"},
            "person": {"type": "keyword"},
            "venue": {"type": "keyword"},
            "type": {"type": "keyword"},
            "url": {"type": "keyword"},
            "note": {"type": "text"},
            "ip": {"type": "keyword", "index": False},
            "created_at": {"type": "date"},
            "status": {"type": "keyword"},
        }
    }
}

def ensure_tips_index(es):
    if not es.indices.exists(index=TIPS_INDEX):
        es.indices.create(index=TIPS_INDEX, mappings=TIPS_SETTINGS["mappings"])

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

def make_client(endpoint=None, api_key=None):
    from elasticsearch import Elasticsearch
    return Elasticsearch(
        endpoint or os.environ["ELASTIC_ENDPOINT"],
        api_key=api_key or os.environ["ELASTIC_API_KEY"],
        request_timeout=30,
    )

def find_edges(es, query, index=INDEX, size=20, role=None, era=None, hood=None):
    """Hybrid RRF: fuzzy keyword + sparse_vector semantic (same as src/es.py).

    role/era/hood: optional facet filters, applied as post_filter — they
    gate the final RRF hit list without touching ranking, so a filtered
    dossier is exactly the unfiltered dossier with rows removed (this ES
    version rejects sparse_vector nested inside bool). Multiple facets
    compose with AND."""
    body = {
        "size": size,
        "retriever": {
            "rrf": {
                "retrievers": [
                    {"standard": {"query": {
                        "bool": {"should": [
                            {"match": {"person_text": {"query": query, "fuzziness": "AUTO"}}},
                            {"match": {"venue_text": {"query": query, "fuzziness": "AUTO"}}},
                            {"match": {"evidence": {"query": query}}},
                        ]},
                    }}},
                    {"standard": {"query": {"sparse_vector": {"field": "semantic", "query": query}}}},
                ],
                "rank_constant": 20,
                "rank_window_size": max(50, size),
            }
        },
    }
    gates = []
    if role:
        gates.append({"term": {"role_bucket": role}})
    if era:
        gates.append({"term": {"era_bucket": era}})
    if hood:
        gates.append({"term": {"venue_hoods": hood}})
    if len(gates) == 1:
        body["post_filter"] = gates[0]
    elif gates:
        body["post_filter"] = {"bool": {"filter": gates}}
    return es.search(index=index, body=body)["hits"]["hits"]

_es = None

def _client():
    global _es
    if _es is None:
        _es = make_client()
    return _es

# ── core logic mirrors ui/server.py (same functions, same behavior) ──
def norm_name(n):
    n = re.sub(r'"[^"]*"', '', n)
    n = n.replace(chr(8217), "'").replace(chr(8216), "'")
    n = n.replace(chr(8220), "'").replace(chr(8221), "'")
    n = re.sub(r"'[^']*'", '', n)
    n = re.sub(r'[^a-z\s-]', '', n.lower())
    return ' '.join(n.split())

def _keysplit(key):
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
    """Same surname and a known nickname pair. Dan is not Danielle."""
    fa, la = _keysplit(ka)
    fb, lb = _keysplit(kb)
    if not fa or not fb or la != lb or fa == fb:
        return False
    return _NICKNAMES.get(fa) == fb or _NICKNAMES.get(fb) == fa

def norm_venue(v):
    import unicodedata as _ud
    v = re.sub(r'\([^)]*\)', ' ', v)
    v = _ud.normalize("NFD", v)
    v = "".join(ch for ch in v if not _ud.combining(ch))
    v = v.replace(chr(8217), "'").replace(chr(8216), "'")
    v = re.sub(r"['’]s?\b", '', v)
    v = re.sub(r'[^a-z0-9\s]', '', v.lower())
    toks = [t for t in v.split() if t not in ("the", "a", "an", "of", "at", "in", "on")]
    return ' '.join(toks)

_GENERIC_VENUE = {"bar", "cafe", "kitchen", "grill", "house", "restaurant", "room", "club", "san", "sf", "food", "wine", "bakery"}

def _venue_touch(va, vb):
    """Leading-token prefix. A single generic token ("bar") does not match."""
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
    return any(_venue_touch(a, b) for a in sa for b in sb)

def venue_history(edges):
    v = set()
    for e in edges:
        for k in ("from_venue", "to_venue"):
            if e.get(k):
                v.add(norm_venue(e[k]))
    return v

def edge_urls(edges):
    return {e["source_url"] for e in edges if e.get("source_url")}

def _components(edges):
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
    while changed:
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
        for c in lone:
            big["names"] |= c["names"]; big["edges"] += c["edges"]
            big["venues"] |= c["venues"]; big["urls"] |= c["urls"]
        big["homonym"] = bool(split)
        for c in split:
            c["homonym"] = True
            clusters.append({"key": key, **c})
        clusters.append({"key": key, **big})

    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                a, b = clusters[i], clusters[j]
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
            if a["key"] != b["key"] and not (a["names"] & b["names"]) \
                    and _fuzzy_sibling(a["key"], b["key"]):
                a.setdefault("possible", set()).add(max(b["names"], key=len))
                b.setdefault("possible", set()).add(max(a["names"], key=len))

    out = []
    for c in clusters:
        counts = {}
        for e in c["edges"]:
            counts[e["person"]] = counts.get(e["person"], 0) + 1
        name = max(sorted(c["names"]), key=lambda n: counts[n])
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
    """True when the stored quotation itself states a career move."""
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
    """sfchronicle | sfgate | eater | other. Unknown hosts are not Eater."""
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
    """Raw role text -> dossier filter bucket. Same logic as ui/server.py —
    keep the two in sync."""
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
        if (era or hood) and es is not None:
            ungated = lineage(es, q, size=25)
            if resolve_query(q, ungated, identity(ungated)):
                return {"query": q, "resolved": False, "lineage": [], "identity": [],
                        "pedigree": None, "facet_empty": True}
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
        # spelling-suggestions one. facet_empty tells the two apart.
        if era or hood:
            return {"query": q, "resolved": False, "lineage": [], "identity": [],
                    "pedigree": None, "facet_empty": bool(
                        _facet_probe(es, q, era=era, hood=hood)) or None if es else None}
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
        out["era_coverage"] = "dates on 15% of cited moves"
    if hood:
        out["hood_filter"] = hood
        # hood stamps exist for SF venues the city file can place — 43% of
        # edge docs — so the filter discloses partial coverage
        out["hood_coverage"] = "neighborhoods on 43% of cited moves"
    return out

def _facet_probe(es, q, era=None, hood=None, role=None):
    """Does the raw query match ANY edge under these facet gates?

    A size=0 window collects NOTHING for post_filter to gate (the RRF
    window is the only pool post_filter sees), so the probe needs a real
    window. Deep one: ES keeps scanning past `size` until the window fills
    with post_filter survivors, so a 300-deep window is an honest
    "any such edge exists" at corpus scale."""
    return bool(find_edges(es, q, size=300, role=role, era=era, hood=hood))

def pedigree(edges):
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
    """evidence is stored in full: citation_supported() must see the whole
    quotation (a move stated past the display cutoff still counts). The
    public payload is shortened for display in assemble_dossier().
    role/era/hood: optional facet filters (roadmap 4.3/4.4), applied inside
    the ES query as post_filter gates."""
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
    body = {"size": limit, "query": {"bool": {"filter": [
        {"terms": {"person.keyword": names}}]}},
        "_source": ["person", "from_venue", "to_venue", "role", "date",
                    "confidence", "source", "action", "evidence", "source_url",
                    "source_image"]}
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
        })
    return out

def _suggest_top(es, prefix, size):
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
    """Venue names only. Not a hybrid dossier search."""
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

def stats(es):
    body = {"size": 0, "aggs": {
        "people": {"cardinality": {"field": "person.keyword"}},
        "from_v": {"terms": {"field": "from_venue.keyword", "size": 500}},
        "to_v": {"terms": {"field": "to_venue.keyword", "size": 500}},
    }}
    r = es.search(index=INDEX, body=body)
    a = r["aggregations"]
    venues = {b["key"] for b in a["from_v"]["buckets"] + a["to_v"]["buckets"] if b["key"]}
    return {"edges": es.count(index=INDEX)["count"],
            "people": a["people"]["value"],
            "venues": len(venues),
            "sources": es.search(
                index=INDEX, body={"size": 0, "aggs": {"s": {"cardinality": {"field": "source_url.keyword"}}}}
            )["aggregations"]["s"]["value"]}

def venues_geo(es=None):
    """Venues for the map — reads the data files bundled next to api/ at
    deploy time (no ES needed)."""
    root = _HERE
    city = os.path.join(root, "city_venues.json")
    curated = os.path.join(root, "venues_geo.json")
    KEEP_TYPES = ("H24", "H25", "H26", "H28", "H29", "H86", "H87", "H88")
    JUNK_WORDS = ("tbd", "to be determined", "facebook", "walgreen", "google",
                  "salesforce", "amazon", "apple inc", "airbnb", "uber",
                  "doordash", "lyft", "bon appetit", "proper food", "mixt",
                  "test ", "unknown")
    CHAIN_NAMES = ("mcdonald", "starbucks", "burger king", "jack in the box",
                   "kentucky fried", "little caesars", "popeyes", "chipotle",
                   "subway", "jamba juice", "peet", "philz", "phil'z", "taco bell",
                   "wendy", "dunkin", "in n out", "mrs field", "cold stone",
                   "dairy queen", "potbelly", "panera", "noah")

    def keep_type(t):
        t = t or ""
        return any(t == k or t.startswith(k + " ") or t.startswith(k + " -")
                   or t.startswith(k + "R") for k in KEEP_TYPES)

    def is_junk(name):
        n = (name or "").lower()
        return any(w in n for w in JUNK_WORDS) or any(c in n for c in CHAIN_NAMES)

    def keep(v):
        if v.get("lineaged") or v.get("michelin"):
            return True
        return keep_type(v.get("permit_type")) and not is_junk(v.get("name"))

    venues = []
    if os.path.exists(city):
        with open(city) as f:
            venues = [v for v in json.load(f)["venues"] if keep(v)]
    if os.path.exists(curated):
        with open(curated) as f:
            by_name = {v["name"].lower(): v for v in venues}
            for v in json.load(f)["venues"]:
                hit = by_name.get(v["name"].lower())
                if hit is None:
                    v.setdefault("lineaged", True)
                    venues.append(v)
                else:
                    if v.get("website"):
                        hit["website"] = v["website"]
    return venues

def _serve_mapjs():
    """map.js with the Mapbox token injected — same trick as ui/server.py's
    index injection, so the token lives only in env + the response body."""
    import os as _os
    mp = _os.path.join(_HERE, "_map.js")
    try:
        with open(mp) as f:
            js = f.read()
    except OSError:
        return (404, {"Content-Type": "text/plain"}, b"not found")
    inject = "window.MAPBOX_TOKEN = %s;\n" % json.dumps(os.environ.get("MAPBOX_TOKEN", ""))
    body = (inject + js).encode()
    return (200, {"Content-Type": "application/javascript; charset=utf-8",
                  "Cache-Control": "public, max-age=300"}, body)

# ── relevance gate: did the query actually name a chef or kitchen we cite? ──
# Hybrid search ranks by relevance, not resolution — a nonsense query still
# returns its 25 nearest records. The dossier UI needs to know whether any
# cluster genuinely IS the query, not merely nearby it.
def resolve_query(q, lin, cl):
    ql = q.lower().strip()
    if not ql:
        return False
    for c in cl:
        for n in [c["name"], *(c.get("aliases") or [])]:
            nl = n.lower()
            if nl == ql and not _is_collective(n):
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

# ── request dispatch (Vercel Python serverless) ──
def _too_many():
    return (429, {"Content-Type": "application/json", "Retry-After": "60"},
            json.dumps({"error": "too many requests"}).encode())

def _dispatch(path, query_params, ip="", body_bytes=None):
    qs = {k: v for k, v in parse_qs(query_params).items()}
    def q1(k):
        v = qs.get(k, [])
        return v[0] if isinstance(v, list) and v else v

    ip = ip or "unknown"
    if path.endswith("/api/search") and not allow_request("search", ip, 30, 60):
        return _too_many()
    if path.endswith("/api/suggest") and not allow_request("suggest", ip, 90, 60):
        return _too_many()
    if path.endswith("/api/tip") and not allow_request("tips", ip, 5, 3600):
        return _too_many()

    try:
        es = _client()
        if path.endswith("/api/search"):
            q = (q1("q") or "").strip()[:MAX_QUERY_LEN]
            size = clamp_size(q1("size"))
            # role facet (roadmap 4.3) + era/hood facets (4.4): filters on the
            # index-time stamps; unknown values are ignored, never 500
            role_raw = (q1("role") or "").strip()
            role = role_raw if role_raw in _ROLE_BUCKETS else None
            era = (q1("era") or "").strip()
            era = era if era in _ERA_BUCKETS else None
            hood = (q1("hood") or "").strip()
            hood = hood if hood in _HOOD_VOCAB else None
            lin = lineage(es, q, size=size, role=role, era=era, hood=hood) if q else []
            cl = identity(lin) if q else []
            need = sorted({n for c in cl if c["homonym"] or c["possible"]
                           for n in [c["name"], *c["aliases"]]})
            if need:
                have = {_edge_key(e) for e in lin}
                extra = [e for e in fetch_person_edges(es, need) if _edge_key(e) not in have]
                if extra:
                    lin = dedupe(lin + extra)
            body = assemble_dossier(q, lin, role=role, era=era, hood=hood, es=es) if q else {
                "query": "", "resolved": False, "lineage": [], "identity": [], "pedigree": None}
        elif path.endswith("/api/suggest"):
            q = (q1("q") or "").strip()[:MAX_QUERY_LEN]
            body = {"query": q, "suggestions": suggest(es, q) if q else []}
        elif path.endswith("/api/venues"):
            body = {"venues": venues_geo()}
        elif path.endswith("/api/stats"):
            body = stats(es)
        elif path.endswith("/api/map.js"):
            return _serve_mapjs()
        elif path.endswith("/api/tip"):
            # Reader-submitted correction/source tip -> tips inbox. Queue,
            # not corpus: nothing enters the lineage index without the
            # citation gate and a human triage pass (src/review_tips.py).
            if not body_bytes or len(body_bytes) > 4096:
                return (400, {"Content-Type": "application/json"},
                        json.dumps({"error": "invalid body"}).encode())
            try:
                payload = json.loads(body_bytes.decode("utf-8", "replace"))
            except Exception:
                return (400, {"Content-Type": "application/json"},
                        json.dumps({"error": "invalid body"}).encode())
            ok, doc_or_err = accept_tip(payload, ip)
            if not ok:
                return (400, {"Content-Type": "application/json"},
                        json.dumps({"error": doc_or_err}).encode())
            if doc_or_err is None:  # honeypot: accepted silently, never stored
                return (200, {"Content-Type": "application/json"},
                        json.dumps({"ok": True}).encode())
            ensure_tips_index(es)
            es.index(index=TIPS_INDEX, document=doc_or_err, refresh=False)
            body = {"ok": True}
        else:
            body = {"error": "unknown endpoint"}
        return (200, {"Content-Type": "application/json"},
                json.dumps(body).encode())
    except Exception:
        # generic error surface: exception text can leak index names / endpoints
        import traceback
        traceback.print_exc()
        return (500, {"Content-Type": "application/json"},
                json.dumps({"error": "search temporarily unavailable"}).encode())

class handler(BaseHTTPRequestHandler):
    """Vercel Python runtime entry point: a BaseHTTPRequestHandler subclass
    delegating to _dispatch(path, query)."""

    def do_GET(self):
        parsed = urlparse(self.path)
        ip = (self.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if not ip and self.client_address:
            ip = self.client_address[0]
        try:
            status, headers, body = _dispatch(parsed.path, parsed.query, ip)
        except Exception:  # belt-and-braces; _dispatch already guards
            status, headers, body = (500, {"Content-Type": "application/json"},
                                     json.dumps({"error": "search temporarily unavailable"}).encode())
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        ip = (self.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if not ip and self.client_address:
            ip = self.client_address[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        body_bytes = self.rfile.read(length) if 0 < length <= 4096 else None
        try:
            status, headers, body = _dispatch(parsed.path, parsed.query, ip, body_bytes)
        except Exception:
            status, headers, body = (500, {"Content-Type": "application/json"},
                                     json.dumps({"error": "search temporarily unavailable"}).encode())
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep function logs lean
        pass
