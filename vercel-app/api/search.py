"""Vercel Python function: every /api/* route (see the rewrites in vercel.json).

All query logic lives in src/dossier.py, shared with the local server
(ui/server.py). build.sh copies it and its sibling modules into api/_lib/,
because the function bundle does not contain src/. In a repo checkout without
that copy (tests, local imports) the source module is used directly.

Credentials come from env vars (ELASTIC_ENDPOINT, ELASTIC_API_KEY,
MAPBOX_TOKEN): never printed, never committed.
"""
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
try:
    from _lib import dossier
except ImportError:  # repo checkout: build.sh has not populated api/_lib/
    sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
    from src import dossier

_es = None


def _client():
    """One client per warm instance."""
    global _es
    if _es is None:
        _es = dossier.make_client()
    return _es


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._handle(None)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        self._handle(self.rfile.read(length) if 0 < length <= 4096 else None)

    def _handle(self, body_bytes):
        parsed = urlparse(self.path)
        ip = (self.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if not ip and self.client_address:
            ip = self.client_address[0]
        status, headers, body = dossier.dispatch(parsed.path, parsed.query, ip, body_bytes, client=_client)
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep function logs lean
        pass
