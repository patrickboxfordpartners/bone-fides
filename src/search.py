"""Search provider chain for venue discovery.

One call site in venue_images.py needs "give me web results for this query".
Which service answers is a deployment detail; this module owns it.

Order: Firecrawl first (real destination URLs, never fabricates an empty result
set), Tavily when Firecrawl's allowance is nearly spent, Bright Data if nothing
else is configured. The fallback is automatic because the failure mode we lived
through was a corpus run dying at venue N with no way to continue: 1,500
Firecrawl credits at 10 per venue is 150 venues, not 4,400.

The important guarantee is `budget()`: a run refuses to start if no provider can
afford it, and prints the arithmetic. Discovering a dead run 75 venues in is a
waste of an hour; discovering it before the first request is a line of text.
"""
import os

from src import firecrawl

try:
    from src import tavily
except Exception:                                    # pragma: no cover
    tavily = None

# Below this many credits, Firecrawl is treated as spent and the chain moves on.
# Sized so the switch happens before a run is mid-venue, not after it fails.
FIRE_CRAWL_FLOOR = 200

# Credits a single venue costs, measured: 1 site search + 3 booking-platform
# searches. Firecrawl bills 2 per search, Tavily 1.
CREDITS_PER_CALL = {"firecrawl": 2, "tavily": 1, "brightdata": 0}
CALLS_PER_VENUE = 4


def _brightdata_configured():
    try:
        from src.brightdata import CREDS
    except Exception:
        return False
    return bool(CREDS.get("BRIGHTDATA_API_KEY"))


def _tavily_available():
    return bool(tavily and tavily.available())


def provider():
    """The provider the NEXT call would use, or None."""
    override = os.environ.get("SEARCH_PROVIDER")
    if override:
        return override.lower()
    if firecrawl.available():
        left = budget()["firecrawl"]["remaining"]
        if left is None or left > FIRE_CRAWL_FLOOR:
            return "firecrawl"
    if _tavily_available():
        return "tavily"
    if _brightdata_configured():
        return "brightdata"
    return None


def budget():
    """Remaining allowance per provider, as {"remaining": int|None}."""
    out = {"firecrawl": {"remaining": None}, "tavily": {"remaining": None},
           "brightdata": {"remaining": None}}
    try:
        out["firecrawl"] = {"remaining": firecrawl.credits_remaining()}
    except Exception:
        pass
    if _tavily_available():
        try:
            out["tavily"] = {"remaining": tavily.usage()["remaining"]}
        except Exception:
            pass
    return out


def affordable(venues):
    """Can the configured providers cover `venues`, and by whom?

    Returns (ok, message).

    An unknown balance is counted as sufficient ONLY for a provider that bills
    nothing we can exhaust (Bright Data, whose allowance failure is a hard error
    rather than a quiet partial). A metered provider with unknown telemetry is
    NOT assumed able to cover a run: that is the hope this function exists to
    replace, and it is exactly how the Bright Data run died at venue 3,600.
    """
    need = venues * CALLS_PER_VENUE
    b = budget()

    order = [p for p in ("firecrawl", "tavily", "brightdata") if provider_ok(p)]
    if not order:
        return False, "no search provider configured"

    # GREEDY across providers, in priority order: Firecrawl pays until it hits
    # its floor, Tavily covers the remainder.
    remaining_venues = venues
    plan = []
    for name in order:
        if remaining_venues <= 0:
            break
        left = b[name]["remaining"]
        if left is None:
            # Bright Data is exhausted and its balance is not queryable, so it
            # cannot be counted as covering anything. It stays in the runtime
            # chain as a last resort, but it must not inflate this plan — which
            # is how the previous run "looked" affordable and died at 3,600.
            plan.append(f"{name}: balance unknown — not counted toward the run")
            continue
        can = left // max(1, CREDITS_PER_CALL[name] * CALLS_PER_VENUE)
        if name == "firecrawl":
            can = max(0, (left - FIRE_CRAWL_FLOOR)) // max(
                1, CREDITS_PER_CALL[name] * CALLS_PER_VENUE)
        take = min(can, remaining_venues)
        if take:
            plan.append(f"{name}: {take} venues ({take * CREDITS_PER_CALL[name] * CALLS_PER_VENUE}"
                        f" of {left} credits)")
            remaining_venues -= take

    if remaining_venues > 0:
        return False, (f"cannot cover {venues} venues — {remaining_venues} uncovered after "
                       + ("; ".join(plan) if plan else "no provider"))
    return True, "; ".join(plan)


def provider_ok(name):
    if name == "firecrawl":
        return firecrawl.available()
    if name == "tavily":
        return _tavily_available()
    if name == "brightdata":
        return _brightdata_configured()
    return False


def search(query, num=20):
    """Web results as [{url, title}]. Raises when no provider can answer.

    Falls through the chain on a provider that is spent or errors. Deliberately
    not a silent [] on total failure: callers distinguish "no answer" from "no
    website", and [] here would erase that at the one place every provider
    agrees on it.
    """
    errors = []
    order = []
    override = os.environ.get("SEARCH_PROVIDER")
    if override:
        order = [override.lower()]
    else:
        if firecrawl.available():
            order.append("firecrawl")
        if _tavily_available():
            order.append("tavily")
        if _brightdata_configured():
            order.append("brightdata")

    for name in order:
        try:
            if name == "firecrawl":
                left = firecrawl.credits_remaining()
                if left is not None and left <= FIRE_CRAWL_FLOOR:
                    errors.append(f"firecrawl: {left} credits left, below floor")
                    continue
                return firecrawl.search(query, num=num)
            if name == "tavily":
                return tavily.search(query, num=num)
            if name == "brightdata":
                from src.brightdata import serp
                return serp(query, num=num)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:80]}")
            continue

    raise RuntimeError(
        "no search provider produced results — " + ("; ".join(errors) or "none configured"))
