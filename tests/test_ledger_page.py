"""The Ledger page holds the structure the plan requires (section 10).

Static checks on ui/ledger.html: the skip link target, the three anchors,
the sortable table with its caption and button headers, the phone sort
chips, the mentor details rows, the starred section, and the API payload
figure the page states.
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
from src import dossier  # noqa: E402
from src import graph  # noqa: E402
from tests.test_graph_api import _get  # noqa: E402
PAGE = os.path.join(_ROOT, "ui", "ledger.html")


def _page():
    return open(PAGE, encoding="utf-8").read()


def test_the_page_names_and_describes_itself():
    p = _page()
    assert "<title>Bone Fides \u2014 The Ledger</title>" in p
    assert 'name="description"' in p


def test_the_skip_link_lands_on_visible_content():
    p = _page()
    assert '<a class="bf-skip" href="#main"' in p
    assert '<main id="main">' in p


def test_the_plan_anchors_exist():
    p = _page()
    for anchor in ('id="kitchens"', 'id="mentors"', 'id="starred"'):
        assert anchor in p, "the page needs a %s anchor" % anchor


def test_the_kitchen_table_has_a_caption_and_button_headers():
    p = _page()
    assert "<caption" in p, "the kitchen table needs a caption"
    heads = re.findall(r'<th scope="col" role="columnheader"><button type="button" '
                       r'class="sortbtn" data-sort="(\w+)"', p)
    assert sorted(heads) == ["alumni", "kitchen", "reach", "starred"]
    assert "Starred within three moves" in p
    assert "starred descendants" not in p, "the mockup label is not used (section 2)"


def test_the_phone_sort_control_is_a_row_of_chips():
    p = _page()
    chips = re.findall(r'data-sort="(\w+)" aria-pressed=', p)
    assert sorted(chips) == ["alumni", "kitchen", "reach", "starred"]
    assert ".sortchips{display:none" in p


def test_mentor_rows_open_in_details_elements():
    p = _page()
    assert "mlist" in p
    # the renderer builds one <details> per mentor with the sample quotations
    assert "<li><details><summary" in p


def test_kitchen_rows_link_to_the_tree_and_the_dossier():
    p = _page()
    assert '"/tree?k=\' + encodeURIComponent(k.slug)' in p
    assert '"/explorer?q=\' + encodeURIComponent(k.name)' in p


def test_starred_rows_link_upward_and_say_when_no_move_exists():
    p = _page()
    assert '"/tree?k=\' + encodeURIComponent(k.slug) + \'&dir=up"' in p
    assert "no cited move yet" in p


def test_the_mentor_note_states_the_limit_figure():
    p = _page()
    assert 'rules.mentor_moves' in p, "the mentor note needs its limit figure"


def test_numbers_use_tabular_numerals():
    p = _page()
    assert "font-variant-numeric:tabular-nums" in p


def test_the_payload_carries_the_displayed_moves_figure():
    status, _, body = _get("/api/ledger", "", "led-p1")
    d = json.loads(body)
    g = graph.load(dossier.data_path("graph.json"))
    assert d["moves_on_display"] == g["raw"]["summary"]["gate_passed"]


def test_the_page_serves_at_its_route():
    # the local server maps the route; the vercel rewrite covers production
    routes = open(os.path.join(_ROOT, "ui", "server.py"), encoding="utf-8").read()
    assert '"/ledger": "ledger.html"' in routes
    v = open(os.path.join(_ROOT, "vercel-app", "vercel.json"), encoding="utf-8").read()
    assert '"source": "/ledger"' in v
    b = open(os.path.join(_ROOT, "vercel-app", "build.sh"), encoding="utf-8").read()
    assert "ledger.html" in b
