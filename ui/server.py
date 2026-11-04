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
            "score": h.get("_score", 0),
        })
    return edges

# Pedigree: source-tier weighting (the triangulation story). The Chronicle is
# the paper of record — a verified personnel change weighs most; SFGate is the
# same newsroom, lighter; Eater moves fastest but is the softest citation.
TIER_WEIGHT = {"sfchronicle": 12, "sfgate": 8, "eater": 6}

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

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        es = self.server.es
        path = urllib.parse.urlsplit(self.path).path  # ignore query string for routing
        if path.startswith("/api/search"):
            self._safe(lambda: self._search(es))
        elif path.startswith("/api/venues"):
            self._safe(lambda: self._json({"venues": venues_geo(es)}))
        elif path.startswith("/api/stats"):
            self._safe(lambda: self._json(stats(es)))
        elif path in ("/", "/index.html"):
            self._serve_index()
        else:
            super().do_GET()

    def _search(self, es):
        m = re.search(r"q=([^&]*)", self.path)
        q = urllib.parse.unquote(m.group(1)) if m else ""
        ms = re.search(r"size=(\d+)", self.path)
        size = min(300, int(ms.group(1))) if ms else 25
        lin = lineage(es, q, size=size) if q else []
        self._json({"query": q, "lineage": lin,
                    "pedigree": pedigree(lin) if q else None,
                    "suggestions": suggest(es, q) if q else []})

    def _safe(self, fn):
        try:
            fn()
        except Exception as e:
            try:
                self._json({"error": str(e)}, status=500)
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
