"""Tavily search client — the second link in the provider chain.

Firecrawl is primary; Tavily is what keeps a corpus run alive when Firecrawl's
monthly allowance is spent rather than dying at venue N. Cheaper per call by an
order of magnitude (1 credit vs 10), which is why it is worth having even as a
fallback.

Two shapes it returns that the call site must NOT see:

  - `tavily.com/knowledge/company/...` pages are Tavily's own internal summaries,
    not destinations. They carry the venue's name, so `_is_official` and
    `_page_names_venue` would happily accept one as the venue's website and
    cache a photo from it. Filtered here.
  - Results arrive in `results`, not `data`, and there is no per-call credit
    count. `usage()` polls the account endpoint, which callers use to decide
    when to switch providers.

Reads TAVILY_API_KEY from bone-fides/.env. Values are never printed.
"""
import json
import os
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENDPOINT = "https://api.tavily.com/search"
USAGE_ENDPOINT = "https://api.tavily.com/usage"

_KEY_FILES = (
    os.path.join(BASE, ".env"),
)


def _load_key():
    for path in _KEY_FILES:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TAVILY_API_KEY=") and "=" in line:
                    v = line.partition("=")[2].strip().strip('"').strip("'")
                    if v:
                        return v
    return None


def available():
    return bool(_load_key())


def _is_internal(url):
    """Tavily's own knowledge pages are summaries OF a company, not its site."""
    return "tavily.com/knowledge/" in (url or "").lower()


def usage():
    """{"remaining": int|None, "plan": str} — remaining may be None when the
    account reports no limit. Never raises: budget reporting must not be able
    to kill a run."""
    key = _load_key()
    if not key:
        return {"remaining": None, "plan": None}
    try:
        req = urllib.request.Request(USAGE_ENDPOINT,
                                     headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return {"remaining": None, "plan": None}
    acct = d.get("account") or {}
    limit, used = acct.get("plan_limit"), acct.get("plan_usage")
    remaining = None
    if isinstance(limit, int) and isinstance(used, int):
        remaining = max(0, limit - used)
    return {"remaining": remaining, "plan": acct.get("current_plan")}


def search(query, num=20, attempts=3, timeout=45):
    """Return [{url, title}] or raise.

    Same contract as firecrawl.search, including the one that matters: an empty
    usable result set RAISES. The caller caches [] as "this venue has no
    website", which is permanent.
    """
    key = _load_key()
    if not key:
        raise RuntimeError("TAVILY_API_KEY is not configured")

    last = None
    for i in range(attempts):
        body = json.dumps({
            "query": query,
            "max_results": max(1, min(num, 20)),
        }).encode()
        req = urllib.request.Request(
            ENDPOINT, data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError(f"Tavily rejected the request ({e.code})")
            if e.code == 429:
                # quota: retrying in seconds will not help, and the chain needs
                # to know so it can switch providers
                raise RuntimeError("Tavily rate/quota limited (429)")
            last = e
            time.sleep(2.0 * (i + 1))
            continue
        except Exception as e:
            last = e
            time.sleep(2.0 * (i + 1))
            continue

        out = []
        for item in (data.get("results") or []):
            url = (item.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            if _is_internal(url):
                continue
            out.append({"url": url, "title": item.get("title") or ""})
        if out:
            return out
        last = RuntimeError("Tavily returned no usable results")
        time.sleep(2.0 * (i + 1))

    raise last or RuntimeError("Tavily search failed")


if __name__ == "__main__":  # smoke test
    hits = search("Absinthe Brasserie San Francisco official website", num=5)
    print(f"Tavily OK: {len(hits)} results · usage {usage()}")
    for h in hits:
        print(" -", h["url"][:90])
