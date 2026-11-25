"""The /numbers endpoint and page (plan section 11).

The payload must answer with the index down: the file-based figures still
arrive, `live` and `fresh` are null, and the reply is never cached. The
page holds one `data-fig` slot per figure, shows an em dash until the
payload arrives, states the honest gaps, and carries no growth-rate
vocabulary. A test forbids the words that would imply one.
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
from src import dossier  # noqa: E402
from tests.test_graph_api import _get  # noqa: E402

PAGE = os.path.join(_ROOT, "ui", "numbers.html")


def _page():
    return open(PAGE, encoding="utf-8").read()


class Down:
    def search(self, **kw):
        raise RuntimeError("index unreachable")

    def count(self, **kw):
        raise RuntimeError("index unreachable")


def _clear_caches():
    # method() and stats() memoize for 300 s; an earlier test may have filled
    # the cache with a working stub client, and the live figures would then
    # answer without ever touching the index we want to see fail
    dossier._METHOD_CACHE["value"] = None
    dossier._STATS_CACHE["value"] = None


def test_numbers_with_the_index_down():
    _clear_caches()
    status, headers, body = _get("/api/numbers", "", "num-1")
    d = json.loads(body)
    hdrs = {k.lower(): v for k, v in headers.items()}
    assert status == 200
    assert d["live"] is None and d["fresh"] is None
    assert hdrs["cache-control"] == "no-store", "a dead index must not be cached"
    assert d["graph"]["gate_passed"] > 0
    assert d["gate"]["precision"] > 0.9
    assert d["booking"]["map_pins"] == len(json.load(
        open(dossier.data_path("venue_booking.json"))))
    assert d["map"]["pins"] > 1000
    assert d["graph"]["bay_area"]["kitchens_placed_sf"] > 0


def test_numbers_live_figures_and_freshness():
    _clear_caches()
    canned = {"coverage": {"edges": 9312, "people": 3119, "venues": 4412,
                           "sources": 2221, "date": 1454, "era_bucket": 1165,
                           "venue_hoods": 3786, "action": 4360, "mentor": 332},
              "tiers": {"eater": 4849, "sfgate": 4425, "sfchronicle": 16,
                        "other": 22}}
    g = dossier._graph()
    # fresh: the index count equals the graph's source moves
    out = dossier._numbers(None)
    assert out["fresh"] is None  # the None client failed; nothing claimed

    def fake_method(es):
        return canned

    real = dossier.method
    dossier.method = fake_method
    try:
        out = dossier._numbers(None)
        assert out["live"]["edges"] == 9312
        assert out["live"]["tiers"]["eater"] == 4849
        assert out["fresh"] is (9312 == g["raw"]["summary"]["source_moves"])
        canned["coverage"]["edges"] = 9400  # the graph is now stale
        out = dossier._numbers(None)
        assert out["fresh"] is False
    finally:
        dossier.method = real
        _clear_caches()


def test_every_figure_is_a_slot_with_an_em_dash():
    p = _page()
    slots = re.findall(r'data-fig="([\w-]+)">&mdash;', p)
    assert len(slots) >= 40, "the page needs its figure slots"
    # no figure is stored in the markup: every data-fig starts empty
    for m in re.finditer(r'data-fig="[\w-]+">([^<]*)<', p):
        assert m.group(1).strip() == "&mdash;", "stored figure: %r" % m.group(1)


def test_the_page_states_the_honest_gaps():
    p = _page()
    gaps = p.split('<ol class="gaps">')[1].split("</ol>")[0]
    assert gaps.count("<li><p>") == 9, "the page must state nine gaps"
    for need in ("does not state the move", "sample measurement",
                 "no timeline claim", "nearly all moves",
                 "no displayed move", "largest connected set",
                 "publication date", "verified of", "no location for a kitchen"):
        assert need in p, "gap missing: %s" % need


def test_the_page_names_the_starred_kitchens_without_a_move_from_the_payload():
    p = _page()
    assert 'data-fig="starred-missing"' in p
    assert "Hilda" not in p, "no starred name may be stored in the page"


def test_the_page_forbids_growth_vocabulary():
    p = _page()
    words = ["customers", "revenue", "users", "traction", "trusted by", "clients"]
    for w in words:
        assert not re.search(r"\b%s\b" % w, p, re.I), "forbidden word: %s" % w


def test_the_contact_link_is_the_owner_address():
    p = _page()
    assert p.count("mailto:") == 1
    assert "mailto:patrick@boxfordpartners.com" in p


def test_the_page_carries_its_sections_and_skip_target():
    p = _page()
    assert '<a class="bf-skip" href="#main"' in p
    assert '<main id="main">' in p
    for anchor in ('id="gate"', 'id="sources"', 'id="coverage"',
                   'id="booking"', 'id="bayarea"', 'id="contact"'):
        assert anchor in p, "missing section %s" % anchor


def test_the_page_says_when_the_graph_is_stale_or_the_live_figures_failed():
    p = _page()
    assert "The graph views were built on" in p
    assert "could not be measured" in p
    assert "The figures could not be loaded" in p
    assert 'id="retry"' in p


def test_the_page_serves_at_its_route():
    routes = open(os.path.join(_ROOT, "ui", "server.py"), encoding="utf-8").read()
    assert '"/numbers": "numbers.html"' in routes
    v = open(os.path.join(_ROOT, "vercel-app", "vercel.json"), encoding="utf-8").read()
    assert '"source": "/numbers"' in v
    b = open(os.path.join(_ROOT, "vercel-app", "build.sh"), encoding="utf-8").read()
    assert "numbers.html" in b
    lim = open(os.path.join(_ROOT, "src", "dossier.py"), encoding="utf-8").read()
    assert '"numbers": ("numbers", 30, 60)' in lim
