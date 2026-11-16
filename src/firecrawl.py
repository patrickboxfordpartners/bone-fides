"""Firecrawl search client for Bone Fides venue discovery.

Replaces Bright Data's SERP zone, which ran out of credits. The call sites in
venue_images.py only ever needed a list of {url, title}, so this module keeps
that contract and nothing above it changes.

Why this is a genuine improvement rather than a swap:

  - Firecrawl returns the REAL destination URL. Bright Data's zone wrapped most
    organic hits in google.com/goto?url=<opaque>, which `_real_url` could only
    recover from display_link/source, so roughly three quarters of results
    arrived as a hostname and a guess.
  - It never returns a well-formed empty result set under load. Bright Data did,
    which find_official_site read as "SERP answered, nothing qualified" and
    cached as a permanent `absent` — that is what flipped 298 venues with
    working images to "no photo" in one run. Here a real query returns fuzzy
    matches, and a genuine transport failure raises, so "failed" and "absent"
    stay distinguishable.

Reads FIRECRAWL_API_KEY from bone-fides/.env, falling back to the
aggressive-sdr fire-enrich project, where the key already exists. Values are
never printed.
"""
import json
import os
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# v2 is the current API (docs.firecrawl.dev/api-reference/v2-introduction).
# The response shape changed with it: v1 returned `data: [...]`, v2 returns
# `data: {web: [...]}` and adds `creditsUsed`, which is what makes a
# 4,400-venue run budgetable instead of a guess.
ENDPOINT = "https://api.firecrawl.dev/v2/search"

# The project's own .env is the source of truth (Firecrawl's onboarding calls
# this Path B: a key in project config, not borrowed across repos). The second
# entry is a migration fallback for the one run that predates the key being
# copied here; it can be deleted once .env has the value.
_KEY_FILES = (
    os.path.join(BASE, ".env"),
    os.path.expanduser("~/aggressive-sdr/fire-enrich/.env.local"),
)


def _load_key():
    for path in _KEY_FILES:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("FIRECRAWL_API_KEY=") and "=" in line:
                    v = line.partition("=")[2].strip().strip('"').strip("'")
                    if v:
                        return v
    return None


def available():
    """True when a key is configured. Callers use this to choose a provider."""
    return bool(_load_key())


def credits_remaining():
    """Credits left this billing period, or None when unknown.

    The chain uses this to decide when to fall through to Tavily. Returning
    None on any failure is deliberate: a telemetry outage must not read as
    "no credits" and silently downgrade every call to the weaker provider.
    """
    key = _load_key()
    if not key:
        return None
    try:
        req = urllib.request.Request(
            "https://api.firecrawl.dev/v2/team/credit-usage",
            headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        v = (d.get("data") or {}).get("remainingCredits")
        return int(v) if v is not None else None
    except Exception:
        return None


# Credits billed since process start. v2 reports `creditsUsed` per call, and a
# full corpus run is the one place the number matters — a resolver asks four
# queries per venue, so "how much will 4,400 venues cost" is answerable only if
# something is counting.
CREDITS_USED = 0


def search(query, num=20, attempts=3, timeout=45):
    """Search the web; return [{url, title}] or raise.

    Mirrors src.brightdata.serp's contract so venue_images can swap one for the
    other. An empty result list RAISES rather than returning []: the caller
    treats [] as "this venue has no website", which is a permanent negative, so
    a request that produced nothing usable must look like a failure, not an
    answer.

    Retries on transport and auth-transient failures. A 401/403 does not retry —
    a bad key will not fix itself within the retry window.
    """
    key = _load_key()
    if not key:
        raise RuntimeError("FIRECRAWL_API_KEY is not configured")

    last = None
    for i in range(attempts):
        body = json.dumps({
            "query": query,
            "limit": max(1, min(num, 100)),
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
            if e.code in (401, 402, 403):
                # auth, quota, or billing: retrying within seconds cannot help
                raise RuntimeError(f"Firecrawl rejected the request ({e.code})")
            last = e
            time.sleep(2.0 * (i + 1))
            continue
        except Exception as e:
            last = e
            time.sleep(2.0 * (i + 1))
            continue

        if not data.get("success", True):
            last = RuntimeError(str(data.get("error") or "Firecrawl search failed"))
            time.sleep(2.0 * (i + 1))
            continue

        global CREDITS_USED
        try:
            CREDITS_USED += int(data.get("creditsUsed") or 0)
        except (TypeError, ValueError):
            pass

        out = []
        # v2 nests results under data.web; v1 had them bare in data. Accept
        # both so a base-URL revert does not silently return zero results.
        payload = data.get("data")
        items = (payload.get("web") if isinstance(payload, dict) else payload) or []
        for item in items:
            url = (item.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            out.append({"url": url, "title": item.get("title") or ""})
        if out:
            return out
        last = RuntimeError("Firecrawl returned no usable results")
        time.sleep(2.0 * (i + 1))

    raise last or RuntimeError("Firecrawl search failed")


if __name__ == "__main__":  # smoke test
    hits = search("Absinthe Brasserie San Francisco official website", num=5)
    print(f"Firecrawl OK: {len(hits)} results")
    for h in hits:
        print(" -", h["url"][:90])
