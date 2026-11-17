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


def active_order():
    """The providers `search()` will actually try, in order.

    ONE definition, used by provider(), capacity(), affordable() and search()
    itself. When capacity() built its own list it counted providers the run
    could never call — with SEARCH_PROVIDER=tavily the plan included Firecrawl's
    credits, so the queue overran Tavily's allowance and the tail of the run
    came back `failed`.
    """
    override = os.environ.get("SEARCH_PROVIDER")
    if override:
        name = override.lower()
        return [name] if provider_ok(name) else []
    order = []
    if firecrawl.available():
        order.append("firecrawl")
    if _tavily_available():
        order.append("tavily")
    if _brightdata_configured():
        order.append("brightdata")
    return order


def provider():
    """The provider the NEXT call would use, or None."""
    order = active_order()
    for name in order:
        if name == "firecrawl":
            left = balance("firecrawl")
            if left is None or left > FIRE_CRAWL_FLOOR:
                return "firecrawl"
            continue
        return name
    return None


# Balances move slowly (a search costs 1-2 credits out of hundreds), and the
# endpoint is a separate round-trip. Checking it before EVERY search added up to
# four 20-second waits per venue if that endpoint stalled while search still
# worked. Cached for BALANCE_TTL seconds; the local spend counter keeps the
# estimate honest in between.
BALANCE_TTL = 120
_balance_cache = {}


def balance(name, force=False):
    """Cached remaining allowance for one provider, or None if unknown.

    The None case is cached too. Caching only SUCCESSES left the stall this
    cache exists for completely unfixed: the endpoint that hangs is the one
    that never writes a cache entry, so a normal venue's four searches still
    waited out four 20-second timeouts — 80 seconds — while search itself was
    fine. An unknown balance is already treated as "assume the provider works"
    by provider() and search(), so remembering the failure changes no decision;
    it only stops re-asking a black hole. `force=True` still goes to the wire,
    which is what the pre-run budget gate uses.
    """
    import time
    now = time.time()
    hit = _balance_cache.get(name)
    if not force and hit and now - hit["at"] < BALANCE_TTL:
        return hit["value"]

    value = None
    try:
        if name == "firecrawl":
            value = firecrawl.credits_remaining()
        elif name == "tavily" and _tavily_available():
            value = tavily.usage()["remaining"]
    except Exception:
        value = None

    _balance_cache[name] = {"at": now, "value": value}
    return value


def budget(force=False):
    """Remaining allowance per provider, as {"remaining": int|None}."""
    out = {}
    for name in ("firecrawl", "tavily", "brightdata"):
        out[name] = {"remaining": balance(name, force=force) if provider_ok(name) else None}
    return out


def _spend(name):
    """Debit the CACHED balance for one call.

    The cache is what keeps a stalled balance endpoint from adding 20 seconds to
    every search. Without this, a cached number would stay stale across a long
    run and the chain would keep thinking Firecrawl had credits it had spent.
    """
    hit = _balance_cache.get(name)
    if hit and hit.get("value") is not None:
        cost = CREDITS_PER_CALL.get(name, 0)
        if cost:
            hit["value"] = max(0, hit["value"] - cost)


def capacity():
    """How many venues the current allowances can cover, and by whom.

    Returns (venues, plan_lines). Separate from affordable() because the monthly
    plan is not "all 4,413 or nothing": each month spends what it has on the
    venues that need it most and the next month continues. A caller that only
    asks "yes/no" would have no way to make progress at all.

    Built from active_order(), the same list search() uses, so the plan can only
    count credits the run is able to spend.
    """
    b = budget()
    order = active_order()
    per_venue = {n: max(1, CREDITS_PER_CALL[n] * CALLS_PER_VENUE) for n in order}

    total, plan = 0, []
    for name in order:
        left = b[name]["remaining"]
        if left is None:
            plan.append(f"{name}: balance unknown — not counted")
            continue
        if name == "firecrawl":
            left = max(0, left - FIRE_CRAWL_FLOOR)
        can = left // per_venue[name]
        if can:
            total += can
            plan.append(f"{name}: {can} venues ({can * per_venue[name]} credits)")
    return total, plan


def affordable(venues):
    """Can the configured providers cover `venues`, and by whom?

    Returns (ok, message). Built from active_order() so it can only promise
    credits the run is able to spend.
    """
    b = budget()
    order = active_order()
    if not order:
        return False, "no search provider configured"

    remaining_venues = venues
    plan = []
    for name in order:
        if remaining_venues <= 0:
            break
        left = b[name]["remaining"]
        if left is None:
            # A balance we cannot read cannot be promised. Counting it as
            # sufficient is how the previous corpus run looked affordable and
            # died at venue 3,600.
            plan.append(f"{name}: balance unknown — not counted")
            continue
        per_venue = max(1, CREDITS_PER_CALL[name] * CALLS_PER_VENUE)
        if name == "firecrawl":
            left = max(0, left - FIRE_CRAWL_FLOOR)
        can = left // per_venue
        take = min(can, remaining_venues)
        if take:
            plan.append(f"{name}: {take} venues ({take * per_venue} of {left} credits)")
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
    order = active_order()          # the ONE list capacity() also budgets from

    for name in order:
        try:
            if name == "firecrawl":
                left = balance("firecrawl")
                if left is not None and left <= FIRE_CRAWL_FLOOR:
                    errors.append(f"firecrawl: {left} credits left, below floor")
                    continue
                out = firecrawl.search(query, num=num)
                _spend(name)
                return out
            if name == "tavily":
                out = tavily.search(query, num=num)
                _spend(name)
                return out
            if name == "brightdata":
                from src.brightdata import serp
                return serp(query, num=num)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:80]}")
            continue

    raise RuntimeError(
        "no search provider produced results — " + ("; ".join(errors) or "none configured"))
