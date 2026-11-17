"""Bright Data SERP client for Bone Fides corpus discovery.

Reads BRIGHTDATA_API_KEY / BRIGHTDATA_SERP_ZONE from bone-fides/.env
(values are never printed). SERP results use the `link` field; google.com/goto
redirect wrappers are dropped.
"""
import json, os, re, ssl, time, urllib.request, urllib.parse

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

def _unwrap(body):
    """Return the parsed SERP document from a Bright Data response.

    The zone is pinned to Raw HTML at the zone level, so `data_format` in the
    request is ignored. `brd_json=1` on the Google URL is what makes the zone
    return parsed JSON instead of the HTML shell. Two shapes arrive:

      {"general":..., "organic":[...]}                 <- parsed SERP
      {"status_code":..., "body": "<html>"}            <- HTML shell, unusable

    The second shape is what a JS-gated or blocked response looks like. It is
    raised as ValueError so callers retry rather than record a false negative.
    """
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("SERP response was not an object")
    if "organic" in data or "general" in data:
        return data
    inner = data.get("body")
    if isinstance(inner, str):
        try:
            parsed = json.loads(inner)
        except json.JSONDecodeError:
            raise ValueError("SERP returned an HTML shell, not parsed results")
        if isinstance(parsed, dict) and ("organic" in parsed or "general" in parsed):
            return parsed
    raise ValueError("SERP response had no organic results field")


def _real_url(o):
    """Recover the destination URL from an organic result.

    Google wraps most organic hits in /goto?url=<opaque blob> when the zone
    scrapes without cookies. The blob is not reversible, but the result still
    carries the real destination in `display_link` ("https://www.benusf.com ›
    reservations") and `source` ("benusf.com"). Dropping those entries threw
    away roughly three quarters of every SERP — which is why discovery looked
    like it was finding almost no sites.
    """
    link = o.get("link") or o.get("url") or ""
    if link and "google.com/goto" not in link:
        return link
    dl = o.get("display_link") or ""
    m = re.match(r"https?://([^/\s›]+)", dl)
    if m:
        host = m.group(1)
        # display_link drops the path; the venue root is enough to verify.
        return "https://" + host + "/"
    src = (o.get("source") or "").strip()
    if "." in src and " " not in src and "google." not in src:
        return "https://" + src + "/"
    return ""


def serp(query, num=20, attempts=4):
    """Google SERP via Bright Data; returns list of {url,title} organic results.

    Retries on transport failure, on the HTML-shell response (roughly a fifth of
    calls at this zone's settings), and on an EMPTY organic list, then raises so
    the caller can tell "no answer" apart from "the venue has no site".

    The empty list is the subtle one. Under load the zone returns a well-formed
    parsed document with `organic: []` — no exception, no HTML. The caller read
    that as "SERP answered clearly and nothing qualified" and cached `absent`,
    which is a permanent negative: a venue that resolves fine was recorded as
    having no photo. 298 venues flipped from a working image to `absent` in one
    concurrent run this way. An empty page-one organic list for a real query
    does not happen; it means the zone declined, so it is retried like a shell.
    """
    google = ("https://www.google.com/search?q=" + urllib.parse.quote(query)
              + f"&hl=en&gl=us&num={num}&brd_json=1")
    last = None
    for i in range(attempts):
        try:
            data = _unwrap(_post({"zone": CREDS["BRIGHTDATA_SERP_ZONE"],
                                  "url": google, "format": "raw"}))
            if not (data.get("organic") or []):
                raise ValueError("SERP returned an empty organic list")
            break
        except Exception as e:          # transport error, HTML shell, or empty
            last = e
            time.sleep(3.0 * (i + 1))     # zone returns empty bodies under load
    else:
        raise last or RuntimeError("SERP failed")
    out, seen = [], set()
    for o in (data.get("organic") or []):
        url = _real_url(o)
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "title": o.get("title") or ""})
    return out

if __name__ == "__main__":
    # smoke test: one cheap SERP call
    r = serp("site:sf.eater.com chef shuffle san francisco", num=8)
    print("SERP OK:", len(r), "results")
    for x in r[:8]:
        print(" -", x["url"][:100])
