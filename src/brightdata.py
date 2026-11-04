"""Bright Data SERP client for Bone Fides corpus discovery.

Reads BRIGHTDATA_API_KEY / BRIGHTDATA_SERP_ZONE from bone-fides/.env
(values are never printed). SERP results use the `link` field; google.com/goto
redirect wrappers are dropped.
"""
import json, os, ssl, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_env_brightdata():
    env = {}
    path = os.path.join(BASE, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line.startswith("BRIGHTDATA_") and "=" in line:
                k, _, v = line.partition("=")
                env[k] = v.strip()
    return env

CREDS = load_env_brightdata()
ENDPOINT = "https://api.brightdata.com/request"

# local python may lack the CA bundle; the endpoint is our own authenticated call
_CTX = ssl.create_default_context()

def _post(payload, timeout=60):
    req = urllib.request.Request(ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + CREDS["BRIGHTDATA_API_KEY"]})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def serp(query, num=20):
    """Google SERP via Bright Data; returns list of {url,title} organic results."""
    google = ("https://www.google.com/search?q=" + urllib.parse.quote(query)
              + f"&hl=en&gl=us&num={num}&brd_json=1")
    body = _post({"zone": CREDS["BRIGHTDATA_SERP_ZONE"], "url": google, "format": "raw"})
    data = json.loads(body)
    if isinstance(data, dict) and isinstance(data.get("body"), str):
        data = json.loads(data["body"])
    out = []
    for o in (data.get("organic") or []):
        link = o.get("link") or o.get("url") or ""
        if not link or "google.com/goto" in link:
            continue
        out.append({"url": link, "title": o.get("title") or ""})
    return out

if __name__ == "__main__":
    # smoke test: one cheap SERP call
    r = serp("site:sf.eater.com chef shuffle san francisco", num=8)
    print("SERP OK:", len(r), "results")
    for x in r[:8]:
        print(" -", x["url"][:100])
