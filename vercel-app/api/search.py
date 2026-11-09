"""Vercel Python function: /api/* handlers, the live ES layer of Bone Fides.

Same query logic as ui/server.py (lineage + identity clustering + pedigree)
but stateless per-request: ES client is cached across warm invocations.
Credentials come from env vars (ELASTIC_ENDPOINT, ELASTIC_API_KEY,
MAPBOX_TOKEN) — never printed, never committed.
"""
import os, sys, json, re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Data files are bundled next to this file via includeFiles.
_HERE = os.path.dirname(os.path.abspath(__file__))

INDEX = "bone-fides-edges"

MAX_QUERY_LEN = 120  # abuse cap: queries are names, not free-text essays

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

def find_edges(es, query, index=INDEX, size=20):
    """Hybrid RRF: fuzzy keyword + sparse_vector semantic (same as src/es.py)."""
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

def _fuzzy_sibling(ka, kb):
    fa, la = _keysplit(ka)
    fb, lb = _keysplit(kb)
    if not fa or not fb or la != lb:
        return False
    return len(fa) >= 3 and len(fb) >= 3 and (fa.startswith(fb) or fb.startswith(fa))

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

def _venue_touch(va, vb):
    if va == vb:
        return True
    ta, tb = set(va.split()), set(vb.split())
    return bool(ta and tb and (ta <= tb or tb <= ta))

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

def pedigree(edges):
    TIER_WEIGHT = {"sfchronicle": 12, "sfgate": 8, "eater": 6}
    if not edges:
        return None
    tiers = {"sfchronicle": 0, "sfgate": 0, "eater": 0}
    total = 0
    urls = set()
    other = 0
    for e in edges:
        t = e.get("source") if e.get("source") in TIER_WEIGHT else "other"
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
def lineage(es, query, size=25):
    hits = find_edges(es, query, size=size)
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
            "evidence": (s.get("evidence") or "")[:220],
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
            "evidence": (s.get("evidence") or "")[:220],
            "source_url": s.get("source_url"),
            "source_image": s.get("source_image"), "score": 0,
        })
    return out

def suggest(es, prefix, size=7):
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
    for e in lin:
        for k in ("from_venue", "to_venue"):
            v = e.get(k)
            if v and v.lower() == ql:
                return True
    # prefix tolerance for plural / partial kitchen names ("Finn Town Taproom")
    for e in lin:
        for k in ("from_venue", "to_venue"):
            v = e.get(k)
            if v and len(ql) >= 4:
                vl = v.lower()
                if vl.startswith(ql) or ql.startswith(vl) and len(vl) >= 4:
                    return True
    return False

# ── request dispatch (Vercel Python serverless) ──
def _dispatch(path, query_params):
    qs = {k: v for k, v in parse_qs(query_params).items()}
    def q1(k):
        v = qs.get(k, [])
        return v[0] if isinstance(v, list) and v else v

    try:
        es = _client()
        if path.endswith("/api/search"):
            q = (q1("q") or "").strip()[:MAX_QUERY_LEN]
            size = min(300, int(q1("size") or 25))
            lin = lineage(es, q, size=size) if q else []
            cl = identity(lin) if q else []
            need = sorted({n for c in cl if c["homonym"] or c["possible"]
                           for n in [c["name"], *c["aliases"]]})
            if need:
                have = {_edge_key(e) for e in lin}
                extra = [e for e in fetch_person_edges(es, need) if _edge_key(e) not in have]
                if extra:
                    lin = dedupe(lin + extra)
                    cl = identity(lin)
            resolved = resolve_query(q, lin, cl) if q else False
            body = {"query": q, "resolved": resolved, "lineage": lin,
                    "identity": [{"name": c["name"], "aliases": c["aliases"],
                                  "homonym": c["homonym"], "possible": c["possible"],
                                  "n": c["n"], "edges": c["edges"]} for c in cl],
                    "pedigree": pedigree(lin) if (q and resolved) else None,
                    "suggestions": suggest(es, q) if q else []}
        elif path.endswith("/api/venues"):
            body = {"venues": venues_geo()}
        elif path.endswith("/api/stats"):
            body = stats(es)
        elif path.endswith("/api/map.js"):
            return _serve_mapjs()
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
        try:
            status, headers, body = _dispatch(parsed.path, parsed.query)
        except Exception:  # belt-and-braces; _dispatch already guards
            status, headers, body = (500, {"Content-Type": "application/json"},
                                     json.dumps({"error": "search temporarily unavailable"}).encode())
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep function logs lean
        pass
