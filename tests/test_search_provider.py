"""Search provider selection and the Firecrawl client contract.

The load-bearing behaviour is NOT that a particular service is called. It is
that an unusable answer never looks like an answer. venue_images caches
"absent" when search returns nothing, and that is permanent — the venue is
never probed again. So the client must raise on every failure mode rather than
return an empty list.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import json

import pytest

from src import firecrawl, search


@pytest.fixture(autouse=True)
def _isolate_balance_cache():
    """The balance cache is module-global and lives for the whole process.

    Without this, one test's mocked balance leaks into the next and the failure
    appears in an unrelated test — which is exactly what happened: a test that
    cached 5 credits left a later test believing Firecrawl was spent.
    """
    import src.search as s
    s._balance_cache.clear()
    yield
    s._balance_cache.clear()


# ── provider selection ──────────────────────────────────────────────────────

def test_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "brightdata")
    assert search.provider() == "brightdata"


def test_firecrawl_is_preferred_when_a_key_exists(monkeypatch):
    """Mock the BALANCE too, not just availability.

    provider() consults the credit balance to decide whether Firecrawl is still
    usable, so a test that only mocks available() calls the live endpoint and
    starts failing once the real account drops below the floor — a test whose
    result changes as money is spent.
    """
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setattr(firecrawl, "available", lambda: True)
    monkeypatch.setattr(firecrawl, "credits_remaining", lambda: 5000)
    monkeypatch.setattr(search, "_balance_cache", {})
    assert search.provider() == "firecrawl"


def test_brightdata_is_the_fallback(monkeypatch):
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setattr(firecrawl, "available", lambda: False)
    monkeypatch.setattr(search, "_tavily_available", lambda: False)
    monkeypatch.setattr(search, "_brightdata_configured", lambda: True)
    assert search.provider() == "brightdata"


def test_no_provider_raises_instead_of_returning_nothing(monkeypatch):
    """Returning [] here would be read by the caller as "no website", which
    gets cached as a permanent absent. A missing key must be loud."""
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setattr(firecrawl, "available", lambda: False)
    monkeypatch.setattr(search, "_tavily_available", lambda: False)
    monkeypatch.setattr(search, "_brightdata_configured", lambda: False)
    assert search.provider() is None
    with pytest.raises(RuntimeError):
        search.search("anything")


# ── the Firecrawl client ────────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, payloads):
    """Make urlopen return the given payloads in order."""
    monkeypatch.setattr(firecrawl, "_load_key", lambda: "fc-test")
    monkeypatch.setattr(firecrawl.time, "sleep", lambda *_: None)
    seq = list(payloads)

    def fake_urlopen(req, timeout=None):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Resp(item)

    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", fake_urlopen)
    return seq


def test_results_shape_matches_the_serp_contract(monkeypatch):
    """Callers read url and title; anything else is ignored."""
    _patch(monkeypatch, [{"success": True, "data": {"web": [
        {"url": "https://absinthe.com/", "title": "Absinthe", "description": "x"},
    ]}}])
    out = firecrawl.search("q")
    assert out == [{"url": "https://absinthe.com/", "title": "Absinthe"}]


def test_non_http_urls_are_dropped(monkeypatch):
    _patch(monkeypatch, [{"success": True, "data": {"web": [
        {"url": "javascript:alert(1)"},
        {"url": "https://ok.com/x", "title": "ok"},
    ]}}])
    assert [r["url"] for r in firecrawl.search("q")] == ["https://ok.com/x"]


def test_empty_result_set_raises_rather_than_returning_empty(monkeypatch):
    """THE regression this file exists for. An empty list is cached by the
    caller as "this venue has no photo" forever; it must look like a failure."""
    _patch(monkeypatch, [{"success": True, "data": {"web": []}}] * 3)
    with pytest.raises(RuntimeError):
        firecrawl.search("q", attempts=3)


def test_all_results_unusable_also_raises(monkeypatch):
    _patch(monkeypatch, [{"success": True, "data": {"web": [{"url": "nope"}]}}] * 2)
    with pytest.raises(RuntimeError):
        firecrawl.search("q", attempts=2)


def test_transport_error_is_retried_then_raises(monkeypatch):
    _patch(monkeypatch, [OSError("boom"), OSError("boom")])
    with pytest.raises(Exception):
        firecrawl.search("q", attempts=2)


def test_empty_then_real_results_is_returned(monkeypatch):
    """A retry that succeeds must not be lost to the earlier empty response."""
    _patch(monkeypatch, [
        {"success": True, "data": {"web": []}},
        {"success": True, "data": {"web": [{"url": "https://absinthe.com/", "title": "A"}]}},
    ])
    assert firecrawl.search("q", attempts=3)[0]["url"] == "https://absinthe.com/"


def test_auth_failure_does_not_retry(monkeypatch):
    """A bad key will not fix itself in two seconds; failing fast keeps a run
    from burning its whole retry budget on a 401."""
    import urllib.error
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(firecrawl, "_load_key", lambda: "bad")
    monkeypatch.setattr(firecrawl.time, "sleep", lambda *_: None)
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError):
        firecrawl.search("q", attempts=5)
    assert calls["n"] == 1, "a 401 must not be retried"


def test_missing_key_is_reported_clearly(monkeypatch):
    monkeypatch.setattr(firecrawl, "_load_key", lambda: None)
    with pytest.raises(RuntimeError, match="FIRECRAWL_API_KEY"):
        firecrawl.search("q")


def test_venue_images_goes_through_the_provider_seam():
    """The resolver must call src.search.search, not a provider directly.

    When it imported src.brightdata.serp, nine booking tests patched that name;
    repointing the call site to a provider module left every patch inert, so
    the tests silently started hitting the live network and "passed" for the
    wrong reason. Pinning the import seam is what makes those patches honest.
    """
    import inspect
    import src.venue_images as v

    for fn in (v.find_official_site, v.find_booking_links):
        src = inspect.getsource(fn)
        assert "from src.search import search" in src, (
            f"{fn.__name__} bypasses the provider seam; tests patching "
            f"src.search.search would no longer intercept it")
        assert "src.brightdata" not in src, (
            f"{fn.__name__} imports a provider directly, reintroducing the "
            f"inert-patch bug")


def test_v2_shape_is_what_the_api_actually_returns(monkeypatch):
    """v2 nests results under data.web and adds creditsUsed.

    v1 returned `data: [...]`. Switching the base URL without handling the new
    shape would return zero results for every query — which the caller reads as
    "no website" and caches forever, the same permanent-negative trap as the
    empty-list bug.
    """
    _patch(monkeypatch, [{"success": True, "creditsUsed": 2, "data": {"web": [
        {"url": "https://www.absinthe.com/", "title": "Absinthe",
         "description": "x", "position": 1},
    ]}}])
    out = firecrawl.search("q")
    assert out == [{"url": "https://www.absinthe.com/", "title": "Absinthe"}]
    assert firecrawl.CREDITS_USED >= 2, "creditsUsed must be accumulated"


def test_v1_shape_still_parses(monkeypatch):
    """A base-URL revert must not silently return zero results."""
    _patch(monkeypatch, [{"success": True, "data": [
        {"url": "https://absinthe.com/", "title": "A"},
    ]}])
    assert firecrawl.search("q")[0]["url"] == "https://absinthe.com/"


def test_the_key_comes_from_the_project_env_first(tmp_path, monkeypatch):
    """Firecrawl's own onboarding is explicit: Path B keeps the key in project
    config. The sibling-repo path is a migration fallback, not a co-equal."""
    env = tmp_path / ".env"
    env.write_text("FIRECRAWL_API_KEY=fc-from-project\n")
    monkeypatch.setattr(firecrawl, "_KEY_FILES", (str(env),))
    assert firecrawl._load_key() == "fc-from-project"


# ── the provider chain ──────────────────────────────────────────────────────

def test_chain_falls_through_a_spent_provider(monkeypatch):
    """The failure this chain exists for: a run dying at venue N.

    Firecrawl at 10 credits/venue covers ~150 venues on a 1,500/month plan, so
    the fallback must be automatic rather than something a human notices.
    """
    import src.search as s

    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setattr(firecrawl, "available", lambda: True)
    monkeypatch.setattr(firecrawl, "credits_remaining", lambda: 5)   # spent
    monkeypatch.setattr(s, "_tavily_available", lambda: True)
    monkeypatch.setattr(s.tavily, "search",
                        lambda q, num=20: [{"url": "https://tavily.example/", "title": "T"}])
    monkeypatch.setattr(firecrawl, "search",
                        lambda q, num=20: pytest.fail("spent provider must not be called"))

    out = s.search("q")
    assert out[0]["url"] == "https://tavily.example/"


def test_chain_prefers_firecrawl_when_it_has_credits(monkeypatch):
    import src.search as s
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setattr(firecrawl, "available", lambda: True)
    monkeypatch.setattr(firecrawl, "credits_remaining", lambda: 5000)
    monkeypatch.setattr(s, "_tavily_available", lambda: True)
    monkeypatch.setattr(s, "balance", lambda name, force=False: 5000 if name == "firecrawl" else None)
    monkeypatch.setattr(firecrawl, "search",
                        lambda q, num=20: [{"url": "https://fc.example/", "title": "F"}])
    monkeypatch.setattr(s.tavily, "search",
                        lambda q, num=20: pytest.fail("Tavily is the fallback"))
    assert s.search("q")[0]["url"] == "https://fc.example/"


def test_chain_reports_every_failure_rather_than_an_empty_list(monkeypatch):
    """An empty list would be cached as "no website" forever."""
    import src.search as s
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setattr(firecrawl, "available", lambda: True)
    monkeypatch.setattr(firecrawl, "credits_remaining", lambda: 5000)
    monkeypatch.setattr(firecrawl, "search",
                        lambda q, num=20: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(s, "_tavily_available", lambda: False)
    monkeypatch.setattr(s, "_brightdata_configured", lambda: False)
    with pytest.raises(RuntimeError) as e:
        s.search("q")
    assert "firecrawl" in str(e.value)


def test_an_unknown_balance_does_not_count_toward_a_run(monkeypatch):
    """Affordability must not be a guess.

    Bright Data's allowance is exhausted and its balance is unqueryable. Treating
    unknown as "sufficient" is how the previous corpus run looked affordable and
    died at venue 3,600.
    """
    import src.search as s
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setattr(firecrawl, "available", lambda: True)
    monkeypatch.setattr(firecrawl, "credits_remaining", lambda: 753)
    monkeypatch.setattr(s, "_tavily_available", lambda: False)
    monkeypatch.setattr(s, "_brightdata_configured", lambda: True)
    monkeypatch.setattr(s, "budget", lambda: {
        "firecrawl": {"remaining": 753}, "tavily": {"remaining": None},
        "brightdata": {"remaining": None}})

    ok, msg = s.affordable(4400)
    assert not ok, "4400 venues cannot be covered by 753 credits"
    assert "not counted" in msg


def test_the_plan_covers_exactly_what_the_balances_allow(monkeypatch):
    import src.search as s
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setattr(firecrawl, "available", lambda: True)
    monkeypatch.setattr(s, "_tavily_available", lambda: True)
    monkeypatch.setattr(s, "_brightdata_configured", lambda: False)
    monkeypatch.setattr(s, "budget", lambda: {
        "firecrawl": {"remaining": 1000}, "tavily": {"remaining": 8700},
        "brightdata": {"remaining": None}})

    ok, msg = s.affordable(400)
    assert ok, msg
    # Firecrawl pays until its floor (1000-200=800 => 100 venues at 8 credits),
    # Tavily covers the other 300 at 4 credits each.
    assert "firecrawl: 100 venues" in msg
    assert "tavily: 300 venues" in msg


# ── monthly batching ────────────────────────────────────────────────────────

def test_capacity_reports_what_the_allowances_cover(monkeypatch):
    """The corpus costs ~44,000 credits and the allowances are in the hundreds,
    so the run is monthly. capacity() is what a batch planner asks."""
    import src.search as s
    monkeypatch.setattr(s, "provider_ok", lambda n: n in ("firecrawl", "tavily"))
    monkeypatch.setattr(s, "budget", lambda: {
        "firecrawl": {"remaining": 1000}, "tavily": {"remaining": 8700},
        "brightdata": {"remaining": None}})

    can, plan = s.capacity()
    # firecrawl pays down to its 200 floor: 800/8 = 100 venues
    # tavily: 8700/4 = 2175 venues
    assert can == 2275, plan
    assert any("firecrawl: 100 venues" in p for p in plan)
    assert any("tavily: 2175 venues" in p for p in plan)


def test_capacity_is_zero_when_nothing_is_affordable(monkeypatch):
    import src.search as s
    monkeypatch.setattr(s, "provider_ok", lambda n: n == "firecrawl")
    monkeypatch.setattr(s, "budget", lambda: {"firecrawl": {"remaining": 150},
                                             "tavily": {"remaining": None},
                                             "brightdata": {"remaining": None}})
    can, plan = s.capacity()
    assert can == 0, "150 credits is below the 200 floor; nothing is affordable"


def test_budget_flag_caps_the_queue_and_says_so(monkeypatch):
    """A monthly run must stop cleanly rather than dying at venue N.

    It also must say how many are deferred, so the next period's operator knows
    the corpus is not finished.
    """
    import inspect
    import src.venue_images as v
    src = inspect.getsource(v.main)
    assert "--budget" in src
    assert "queued for the next period" in src, (
        "the run must report what it deferred, not just what it did")


# ── the balance cache (finding: a stalled endpoint must not stall search) ───

def test_balance_is_cached_rather_than_fetched_per_search(monkeypatch):
    """The balance endpoint is a separate round-trip with a 20s timeout.

    Checking it before every search added up to 80 seconds of dead waiting per
    venue when that endpoint stalled while search itself still worked.
    """
    import src.search as s
    monkeypatch.setattr(s, "firecrawl", firecrawl)
    monkeypatch.setattr(s, "_balance_cache", {})

    calls = {"n": 0}

    def fake():
        calls["n"] += 1
        return 900

    monkeypatch.setattr(firecrawl, "credits_remaining", fake)
    assert s.balance("firecrawl") == 900
    assert s.balance("firecrawl") == 900
    assert s.balance("firecrawl") == 900
    assert calls["n"] == 1, "the balance must be cached, not re-fetched per search"


def test_cached_balance_is_debited_by_local_spend(monkeypatch):
    """A cached number must not stay stale through a long run, or the chain
    keeps believing Firecrawl has credits it has already spent."""
    import src.search as s
    monkeypatch.setattr(s, "_balance_cache", {"firecrawl": {"at": 1e12, "value": 500}})
    s._spend("firecrawl")
    s._spend("firecrawl")
    assert s._balance_cache["firecrawl"]["value"] == 500 - 2 * s.CREDITS_PER_CALL["firecrawl"]


def test_capacity_uses_the_same_provider_list_as_search(monkeypatch):
    """The finding: with SEARCH_PROVIDER=tavily, capacity() also counted
    Firecrawl's credits, so --budget queued more venues than the run could pay
    for and the tail came back `failed`."""
    import src.search as s
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setattr(s, "provider_ok", lambda n: n in ("firecrawl", "tavily"))
    monkeypatch.setattr(s, "budget", lambda force=False: {
        "firecrawl": {"remaining": 1000}, "tavily": {"remaining": 400},
        "brightdata": {"remaining": None}})
    monkeypatch.setattr(s, "_balance_cache", {})

    can, plan = s.capacity()
    assert can == 100, plan                      # 400 credits / 4 per venue
    assert all("firecrawl" not in p for p in plan), (
        "capacity must not count a provider the run cannot call")


def test_affordable_refuses_a_run_it_cannot_pay_for(monkeypatch):
    import src.search as s
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setattr(s, "provider_ok", lambda n: n == "tavily")
    monkeypatch.setattr(s, "budget", lambda force=False: {
        "firecrawl": {"remaining": None}, "tavily": {"remaining": 40},
        "brightdata": {"remaining": None}})
    ok, why = s.affordable(100)                  # 100 venues need 400 credits
    assert not ok
    assert "uncovered" in why
