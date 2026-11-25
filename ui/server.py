"""Bone Fides local demo server: static pages from ui/ plus the /api/* routes.

All query logic lives in src/dossier.py, shared with the Vercel function
(vercel-app/api/search.py). This file only maps HTTP onto it.

Run:  .venv/bin/python ui/server.py   ->  http://127.0.0.1:8017
"""
import json
import os
import sys
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src.cli import load_env  # noqa: E402

load_env(os.path.join(BASE, ".env"))

from src import dossier  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))

# Same page routes as the rewrites in vercel-app/vercel.json.
PAGES = {
    "/": "landing.html", "/landing": "landing.html", "/landing.html": "landing.html",
    "/tree": "tree.html", "/tree.html": "tree.html",
    "/explorer": "explorer.html", "/explorer/": "explorer.html",
    "/explorer.html": "explorer.html", "/explorer/index.html": "explorer.html",
    "/method": "method.html", "/method.html": "method.html",
}


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        if parts.path.startswith("/api/"):
            self._api(parts)
        elif parts.path in PAGES:
            self._serve_page(PAGES[parts.path])
        else:
            super().do_GET()

    def do_POST(self):
        parts = urllib.parse.urlsplit(self.path)
        if not parts.path.startswith("/api/"):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(length) if 0 < length <= 4096 else None
        self._api(parts, body)

    def _client_ip(self):
        fwd = self.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
        return self.client_address[0] if self.client_address else ""

    def _api(self, parts, body=None):
        status, headers, payload = dossier.dispatch(
            parts.path, parts.query, self._client_ip(), body, client=lambda: self.server.es)
        self._send(status, headers, payload)

    def _serve_page(self, name):
        try:
            with open(os.path.join(ROOT, name)) as f:
                html = f.read()
        except OSError:
            self.send_error(404)
            return
        if name == "explorer.html":
            inject = "<script>window.MAPBOX_TOKEN = %s;</script>" % json.dumps(os.environ.get("MAPBOX_TOKEN", ""))
            html = html.replace("</head>", inject + "</head>", 1)
        self._send(200, {"Content-Type": "text/html; charset=utf-8"}, html.encode())

    def _send(self, status, headers, body):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # keep demo console clean


def main(port=8017):
    os.chdir(ROOT)  # static files resolve relative to ui/, regardless of launch dir
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.es = dossier.make_client()
    print(f"Bone Fides: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
