"""Search provider selection for venue discovery.

One call site in venue_images.py needs "give me web results for this query".
Which service answers that is a deployment detail, so it is chosen here rather
than hardcoded at the call site.

Order: Firecrawl if a key is configured, else Bright Data if it is. Firecrawl
first because it returns the real destination URL and never fabricates an empty
result set — both of which were live failure modes with the Bright Data zone.

If neither is configured this raises at call time with a clear message, rather
than silently returning no results (which the resolver would cache as "this
venue has no photo" — the exact permanent-negative bug this module's callers
already guard against).
"""
import os

from src import firecrawl


def _brightdata_configured():
    try:
        from src.brightdata import CREDS
    except Exception:
        return False
    return bool(CREDS.get("BRIGHTDATA_API_KEY"))


def provider():
    """Name of the provider that will be used, or None."""
    if os.environ.get("SEARCH_PROVIDER"):        # explicit override wins
        return os.environ["SEARCH_PROVIDER"].lower()
    if firecrawl.available():
        return "firecrawl"
    if _brightdata_configured():
        return "brightdata"
    return None


def search(query, num=20):
    """Web results as [{url, title}]. Raises when no provider is usable.

    Deliberately not a silent [] on failure: callers distinguish "no answer"
    from "no website", and returning [] here would erase that distinction at
    the one place both providers agree on it.
    """
    choice = provider()
    if choice == "firecrawl":
        return firecrawl.search(query, num=num)
    if choice == "brightdata":
        from src.brightdata import serp
        return serp(query, num=num)
    raise RuntimeError(
        "no search provider configured: set FIRECRAWL_API_KEY (preferred) or "
        "BRIGHTDATA_API_KEY")
