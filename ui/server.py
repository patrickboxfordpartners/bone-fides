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
            "evidence": (s.get("evidence") or "")[:220],
            "source_url": s.get("source_url"),
            "score": h.get("_score", 0),
        })
    return edges

def venues_geo(es):
    """Venues + cached geocodes for the map (ui/venues_geo.json, written by ui/geocode.py)."""
    cache = os.path.join(ROOT, "venues_geo.json")
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)["venues"]
    return []

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
            "sources": len({b["key"] for b in es.search(
                index=INDEX, body={"size": 0, "aggs": {"s": {"terms": {"field": "source_url.keyword", "size": 500}}}}
            )["aggregations"]["s"]["buckets"]})}

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        es = self.server.es
        if self.path.startswith("/api/search"):
            self._safe(lambda: self._search(es))
        elif self.path.startswith("/api/venues"):
            self._safe(lambda: self._json({"venues": venues_geo(es)}))
        elif self.path.startswith("/api/stats"):
            self._safe(lambda: self._json(stats(es)))
        elif self.path in ("/", "/index.html"):
            self._serve_index()
        else:
            super().do_GET()

    def _search(self, es):
        m = re.search(r"q=([^&]*)", self.path)
        q = urllib.parse.unquote(m.group(1)) if m else ""
        ms = re.search(r"size=(\d+)", self.path)
        size = min(300, int(ms.group(1))) if ms else 25
        self._json({"query": q, "lineage": lineage(es, q, size=size) if q else [],
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
