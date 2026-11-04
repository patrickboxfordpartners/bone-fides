"""Bright Data SERP + fetch client for Bone Fides corpus growth.

Reads BRIGHTDATA_API_KEY / BRIGHTDATA_SERP_ZONE from the env file the user
pointed us at (~/clones/boxford-crm-brightdata/.env) — values are never printed.
"""
import json, os, time
import urllib.request

ENV_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
    os.path.expanduser("~/clones/boxford-crm-brightdata/.env"),
]

def _load_creds():
    for path in ENV_CANDIDATES:
        if not os.path.exists(path):
            continue
        creds = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("BRIGHTDATA_"):
                    k, _, v = line.partition("=")
                    creds[k] = v.strip().strip('"').strip("'")
        if creds.get("BRIGHTDATA_API_KEY") and creds.get("BRIGHTDATA_SERP_ZONE"):
            return creds
    raise RuntimeError("no BRIGHTDATA_API_KEY/BRIGHTDATA_SERP_ZONE in candidate env files")

CREDS = _load_creds()
ENDPOINT = "https://api.brightdata.com/request"

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
        if o.get("url"):
            out.append({"url": o["url"], "title": o.get("title") or ""})
    return out

def fetch_page(url, timeout=90):
    """Fetch a page through Bright Data SERP zone unlocker; returns HTML text or None."""
    try:
        html = _post({"zone": CREDS["BRIGHTDATA_SERP_ZONE"],
                      "url": url, "format": "raw"}, timeout=timeout)
        return html if len(html) > 500 else None
    except Exception as e:
        print("  fetch fail:", url[:90], type(e).__name__, str(e)[:120])
        return None

if __name__ == "__main__":
    import urllib.parse
    # smoke test: one cheap SERP call
    r = serp("site:sf.eater.com chef shuffle san francisco", num=5)
    print("SERP OK:", len(r), "results")
    for x in r[:5]:
        print(" -", x["url"][:100])
