"""Bone Fides demo UI: static page + JSON query API against the lineage index."""
import os, sys, json, re, urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src.cli import load_env
load_env(os.path.join(BASE, ".env"))

from src.es import make_client, find_edges, INDEX

ROOT = os.path.dirname(os.path.abspath(__file__))

def suggest(es, prefix, size=7):
    """Venue/person suggestions for the search box."""
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

def lineage(es, query, size=25):
    """All edges matching a venue or person, split into inbound/outbound by the UI."""
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

# Pedigree: source-tier weighting (the triangulation story). The Chronicle is
# the paper of record — a verified personnel change weighs most; SFGate is the
# same newsroom, lighter; Eater moves fastest but is the softest citation.
TIER_WEIGHT = {"sfchronicle": 12, "sfgate": 8, "eater": 6}

def norm_name(n):
    """Canonical person-name key: drop quoted nicknames, straighten quotes,
    lowercase, strip punctuation. 'Traci des Jardins' == 'Traci Des Jardins',
    "Sean O'Brien" == 'Sean O’Brien', "Thitid 'Ton' Tassanakajohn" collapses."""
    import re as _re
    n = _re.sub(r'"[^"]*"', '', n)
    n = n.replace(chr(8217), "'").replace(chr(8216), "'")
    n = n.replace(chr(8220), "'").replace(chr(8221), "'")  # curly double -> straight
    n = _re.sub(r"'[^']*'", '', n)
    n = _re.sub(r'[^a-z\s-]', '', n.lower())
    return ' '.join(n.split())

def norm_venue(v):
    """Normalized venue key for overlap matching only (never displayed):
    drop parenthetical annotations (Saison (2124 Folsom St.) == Saison),
    trailing possessives (Chez TJ's == Chez TJ), unicode-fold accents
    (Jardinière == Jardiniere), straighten apostrophes, strip punctuation,
    drop stop words (The Commissary == Commissary)."""
    import re as _re, unicodedata as _ud
    v = _re.sub(r'\([^)]*\)', ' ', v)                     # (Folsom St. location)
    v = _ud.normalize("NFD", v)
    v = "".join(ch for ch in v if not _ud.combining(ch))
    v = v.replace(chr(8217), "'").replace(chr(8216), "'")
    v = _re.sub(r"['’]s?\b", '', v)                       # possessive TJ's -> TJ
    v = _re.sub(r'[^a-z0-9\s]', '', v.lower())
    toks = [t for t in v.split() if t not in ("the", "a", "an", "of", "at", "in", "on")]
    return ' '.join(toks)

def _venue_touch(va, vb):
    """Two venue keys touch on exact equality OR token containment
    (Betelnut ⊂ Betelnut Pejiu Wu, Ritz Carlton ⊂ Ritz Carlton Buckhead)."""
    if va == vb:
        return True
    ta, tb = set(va.split()), set(vb.split())
    return bool(ta and tb and (ta <= tb or tb <= ta))

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

def _fuzzy_sibling(ka, kb):
    """True if two normalized name keys are initial-prefix compatible variants
    of one name: same surname, first names >=3 chars with one a prefix of the
    other (jennifer/jen, joshua/josh, christopher/chris). Bare initials are
    never matched — 'M. Miller' could be Mike or Mary."""
    fa, la = _keysplit(ka)
    fb, lb = _keysplit(kb)
    if not fa or not fb or la != lb:
        return False
    return len(fa) >= 3 and len(fb) >= 3 and (fa.startswith(fb) or fb.startswith(fa))

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
                if a["key"] != b["key"] and _fuzzy_sibling(a["key"], b["key"]) \
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

def pedigree(edges):
    """Weighted credibility score for the queried kitchen/person, 0-100.

    Three factors: authority (how Chronicle-weighted the citations are,
    55pts), independent corroboration across sources (25pts), and depth of
    the record (20pts). A thin single-Eater-article venue lands ~29; a
    Chronicle-verified, multi-source, deep record approaches 100."""
    if not edges:
        return None
    tiers = {"sfchronicle": 0, "sfgate": 0, "eater": 0}
    total = 0
    urls = set()
    for e in edges:
        t = e.get("source") if e.get("source") in TIER_WEIGHT else "eater"
        tiers[t] += 1
        total += TIER_WEIGHT[t]
        if e.get("source_url"):
            urls.add(e["source_url"])
    authority = total / (len(edges) * TIER_WEIGHT["sfchronicle"])
    corroboration = min(1.0, max(0, len(urls) - 1) / 4)
    depth = min(1.0, len(edges) / 12)
    score = round(55 * authority + 25 * corroboration + 20 * depth)
    return {"score": min(100, score),
            "moves": len(edges), "sources": len(urls), "tiers": tiers}

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

    JUNK_WORDS = ("tbd", "to be determined", "facebook", "walgreen", "google",
                  "salesforce", "amazon", "apple inc", "airbnb", "uber",
                  "doordash", "lyft", "bon appetit", "proper food", "mixt",
                  "test ", "unknown")
    CHAIN_NAMES = ("mcdonald", "starbucks", "burger king", "jack in the box",
                   "kentucky fried", "little caesars", "popeyes", "chipotle",
                   "subway", "jamba juice", "peet", "philz", "phil'z", "taco bell",
                   "wendy", "dunkin", "in n out", "mrs field", "cold stone",
                   "dairy queen", "potbelly", "panera", "noah")

    def is_junk(name):
        n = (name or "").lower()
        return any(w in n for w in JUNK_WORDS) or any(c in n for c in CHAIN_NAMES)

    def keep(v):
        if v.get("lineaged") or v.get("michelin"):
            return True
        return keep_type(v.get("permit_type")) and not is_junk(v.get("name"))

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
        k = _edge_key(person_fix(e))
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out

def person_fix(e):
    return e

def fetch_person_edges(es, names, limit=100):
    """Full edge set for exact person strings — targeted completion when the
    search-ranked slice fragments a chef's record (name variants, possible
    splits). A bridge edge the hybrid ranking missed can reconnect them."""
    body = {"size": limit, "query": {"bool": {"filter": [
        {"terms": {"person.keyword": names}}]}},
        "_source": ["person", "from_venue", "to_venue", "role", "date",
                    "confidence", "source", "action", "evidence", "source_url"]}
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

def stats(es):
    """Top-line corpus stats for the masthead counter."""
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

MAX_QUERY_LEN = 120  # abuse cap: queries are names, not free-text essays

def resolve_query(q, lin, cl):
    """Did the query actually name a cited chef or kitchen? Same logic as
    vercel-app/api/search.py — keep the two in sync."""
    ql = q.lower().strip()
    if not ql:
        return False
    for c in cl:
        for n in [c["name"], *(c.get("aliases") or [])]:
            if n.lower() == ql:
                return True
    for e in lin:
        for k in ("from_venue", "to_venue"):
            v = e.get(k)
            if v and v.lower() == ql:
                return True
    for e in lin:
        for k in ("from_venue", "to_venue"):
            v = e.get(k)
            if v and len(ql) >= 4:
                vl = v.lower()
                if vl.startswith(ql) or ql.startswith(vl) and len(vl) >= 4:
                    return True
    return False

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        es = self.server.es
        path = urllib.parse.urlsplit(self.path).path  # ignore query string for routing
        if path.startswith("/api/search"):
            self._safe(lambda: self._search(es))
        elif path.startswith("/api/venues"):
            self._safe(lambda: self._json({"venues": venues_geo(es)}))
        elif path.startswith("/api/map.js"):
            self._serve_mapjs()
        elif path.startswith("/api/stats"):
            self._safe(lambda: self._json(stats(es)))
        elif path in ("/", "/index.html"):
            self._serve_index()
        else:
            super().do_GET()

    def _search(self, es):
        m = re.search(r"q=([^&]*)", self.path)
        q = urllib.parse.unquote(m.group(1)) if m else ""
        q = q.strip()[:MAX_QUERY_LEN]
        ms = re.search(r"size=(\d+)", self.path)
        size = min(300, int(ms.group(1))) if ms else 25
        lin = lineage(es, q, size=size) if q else []
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
                lin = dedupe(lin + extra)
                cl = identity(lin)
        resolved = resolve_query(q, lin, cl) if q else False
        self._json({"query": q, "resolved": resolved, "lineage": lin,
                    "identity": [{"name": c["name"], "aliases": c["aliases"],
                                  "homonym": c["homonym"], "possible": c["possible"],
                                  "n": c["n"], "edges": c["edges"]} for c in cl],
                    "pedigree": pedigree(lin) if (q and resolved) else None,
                    "suggestions": suggest(es, q) if q else []})

    def _safe(self, fn):
        try:
            fn()
        except Exception:
            # generic error surface: exception text can leak index names/endpoints
            try:
                self._json({"error": "search temporarily unavailable"}, status=500)
            except Exception:
                pass

    def _serve_index(self):
        """Serve index.html with the Mapbox token injected as window.MAPBOX_TOKEN."""
        try:
            with open(os.path.join(ROOT, "index.html")) as f:
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
