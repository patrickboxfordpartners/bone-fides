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


# ── provider selection ──────────────────────────────────────────────────────

def test_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "brightdata")
    assert search.provider() == "brightdata"


def test_firecrawl_is_preferred_when_a_key_exists(monkeypatch):
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setattr(firecrawl, "available", lambda: True)
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
