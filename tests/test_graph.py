"""The graph module's tree and node logic, on a small fixture graph
(docs/flagship/plan.md section 16).

The tree is a breadth-first tree: each kitchen once, at its smallest depth,
the parent the first in key order; totals are computed before the 300-node
cut; each child's via moves join exactly its parent and itself.
"""
import json
import os
import random
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
from src import graph  # noqa: E402


def _k(key, name, slug, stars=0):
    return [key, name, slug, stars, []]


def _m(pid, fi, ti, quote="q", role="chef", year=None, outlet="eater",
       url="https://sf.eater.com/a", score=2):
    return [pid, fi, ti, role, year, outlet, url, quote, None, "high", "JOINED", score, "tenure"]


def _g():
    """root --a--> A --b--> B, and root --c--> C; a second component D--E."""
    raw = {
        "v": 1, "built_at": "2026-01-01",
        "summary": {"moves_kept": 4, "moves_with_year": 1},
        "kitchens": [_k("root", "Root Kitchen", "root"),
                     _k("a", "Alpha", "alpha", 3),
                     _k("b", "Beta", "beta"),
                     _k("c", "Gamma", "gamma", 1),
                     _k("d", "Delta", "delta"),
                     _k("e", "Epsilon", "epsilon")],
        "people": [["p1", "Person One", False], ["p2", "Person Two", True]],
        "moves": [_m("p1", 0, 1), _m("p2", 1, 2, quote="second", year="2019"),
                  _m("p1", 0, 3, quote="third"), _m("p2", 4, 5, quote="other side")],
        "hop_index": {"0:1": [0], "1:2": [1], "0:3": [2], "4:5": [3]},
    }
    return raw


def _load(raw):
    path = os.path.join(tempfile.mkdtemp(), "graph.json")
    with open(path, "w") as f:
        json.dump(raw, f)
    return graph.load(path)


def test_tree_generations_and_reach():
    t = graph.tree(_load(_g()), "root")
    assert t["resolved"] is True
    assert t["summary"]["generations"] == [2, 1, 0]
    assert t["summary"]["reach"] == 4       # root + A + B + C
    assert t["root"]["name"] == "Root Kitchen"
    names = [c["name"] for c in t["children"]]
    assert names == ["Alpha", "Gamma"]      # starred first


def test_each_child_has_via_moves_that_join_its_two_kitchens():
    t = graph.tree(_load(_g()), "root")
    a = t["children"][0]
    assert a["name"] == "Alpha"
    assert a["via"][0]["person"] == "Person One"
    b = a["children"][0]
    assert b["name"] == "Beta"
    assert b["via"][0]["person"] == "Person Two"
    assert b["via"][0]["year"] == "2019"


def test_dir_up_is_the_mirror():
    t = graph.tree(_load(_g()), "beta", direction="up")
    assert t["summary"]["reach"] == 3        # beta -> alpha -> root
    assert [c["name"] for c in t["children"]] == ["Alpha"]
    assert t["children"][0]["children"][0]["name"] == "Root Kitchen"


def test_a_cycle_ends_at_the_smallest_depth():
    raw = _g()
    raw["moves"].append(_m("p1", 2, 0, quote="cycle"))
    raw["hop_index"]["2:0"] = [4]
    t = graph.tree(_load(raw), "root")
    assert t["summary"]["reach"] == 4        # beta does not come back as a child


def test_the_node_cut_keeps_the_totals():
    raw = _g()
    # a star wider than the cut: root with 320 first-move kitchens
    n = 320
    for i in range(4, n):
        raw["kitchens"].append(_k("n%d" % i, "N%d" % i, "n%d" % i))
        raw["moves"].append(_m("p1", 0, i, quote="star"))
        raw["hop_index"]["0:%d" % i] = [len(raw["moves"]) - 1]
    orig = graph.MAX_NODES
    graph.MAX_NODES = 10
    try:
        t = graph.tree(_load(raw), "root")
        assert t["summary"]["truncated"] is True
        assert t["summary"]["reach"] == n - 4 + 4   # total computed before the cut
        kept = 1 + len(t["children"])
        assert kept <= 10
    finally:
        graph.MAX_NODES = orig


def test_unresolved_names_return_none_and_suggestions():
    g = _load(_g())
    assert graph.tree(g, "No Such Kitchen") is None
    assert [s["name"] for s in graph.unresolved(g, "alph")] == ["Alpha"]


def test_nodes_prefix_match_and_near():
    g = _load(_g())
    out = graph.nodes(g, "alp", kind="kitchen")
    assert [n["name"] for n in out] == ["Alpha"]
    near = graph.nodes(g, "bet", kind="kitchen", near=graph._resolve(g, "delta"))
    assert near[0]["joined"] is False        # beta and delta are not connected
    near2 = graph.nodes(g, "bet", kind="kitchen", near=graph._resolve(g, "root"))
    assert near2[0]["joined"] is True


def test_nodes_chefs_carry_up_to_two_kitchens():
    g = _load(_g())
    out = graph.nodes(g, "person one", kind="chef")
    assert out and out[0]["note"]


def test_a_shorter_spelling_resolves_to_the_same_kitchen():
    raw = _g()
    raw["kitchens"][0] = ["root", "Root Kitchen", "root", 0,
                          ["The Root Kitchen", "Root Kitchn"]]
    g = _load(raw)
    assert graph._resolve(g, "The Root Kitchen") == 0
    assert graph._resolve(g, "root") == 0
    assert graph._resolve(g, "root-kitchen") is not None
