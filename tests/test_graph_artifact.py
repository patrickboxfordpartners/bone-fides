"""Honesty checks on the committed ui/graph.json (plan section 16).

Every shipped move passes the gate and names a person; every kitchen is a
named kitchen whose key equals venue_key of its display name; the summary
equals a recount; the showpiece figures are re-counted by an independent
breadth-first walk written in this file, not typed.
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
from src import dossier, graph  # noqa: E402

GRAPH = dossier.data_path("graph.json")
STAMP = os.path.join(os.path.dirname(_HERE), "ui", "gate_stamp.json")


def _raw():
    with open(GRAPH, encoding="utf-8") as f:
        return json.load(f)


def test_the_file_exists_loads_fast_and_stays_small():
    assert os.path.exists(GRAPH)
    assert os.path.getsize(GRAPH) < 4 * 1024 * 1024
    t0 = time.time()
    g = graph.load(GRAPH)
    dt = time.time() - t0
    assert dt < 0.5          # cold parse of the real file, generous bound
    assert len(g["kitchens"]) > 1000


def _spellings(g, i):
    """A node's display name and its other recorded spellings."""
    k = g["kitchens"][i]
    return [k[1]] + list(k[4])


def test_every_move_passes_the_gate_and_names_a_person():
    g = graph.load(GRAPH)
    for row in g["moves"]:
        person = g["by_pid"].get(row[0], [row[0], row[0], False])[1]
        assert dossier._is_named_person(person), person
        assert str(row[6]).startswith("http"), row[6]
        # the quote names the kitchen in one of its recorded spellings;
        # the move passes under that spelling, as it was extracted
        froms = _spellings(g, row[1]) if row[1] >= 0 else [None]
        tos = _spellings(g, row[2]) if row[2] >= 0 else [None]
        ok = False
        for fv in froms:
            for tv in tos:
                edge = {"person": person, "from_venue": fv, "to_venue": tv,
                        "role": row[3], "action": row[10], "evidence": row[7]}
                if dossier.citation_reason(edge) is not None:
                    ok = True
                    break
            if ok:
                break
        assert ok, row[7][:60]


def test_every_kitchen_is_named_and_its_key_matches_its_name():
    g = graph.load(GRAPH)
    for key, name, slug, stars, _ in g["kitchens"]:
        assert dossier.is_named_kitchen(name), name
        assert dossier.venue_key(name) == key, (name, key)


def test_the_summary_equals_a_recount_from_the_rows():
    raw = _raw()
    s = raw["summary"]
    assert s["source_moves"] == 9312
    assert s["moves_kept"] == len(raw["moves"])
    hop_pairs = list(raw["hop_index"].items())
    assert s["hops"] == sum(len(v) for v in raw["hop_index"].values())
    assert s["kitchens_linked"] == len({i for pair in hop_pairs
                                        for i in (int(pair[0].split(":")[0]),
                                                  int(pair[0].split(":")[1]))})
    assert s["people"] == len(raw["people"])
    assert s["moves_with_year"] == sum(1 for r in raw["moves"] if r[4])


def test_gate_passed_matches_the_gate_stamp():
    raw = _raw()
    with open(STAMP, encoding="utf-8") as f:
        stamp = json.load(f)
    if raw["summary"]["source_moves"] == stamp["on_record"]:
        assert raw["summary"]["gate_passed"] == stamp["displayed"]


def test_every_starred_row_is_a_node_or_is_listed_missing():
    import json as _json
    cv = _json.load(open(dossier.data_path("city_venues.json"), encoding="utf-8"))["venues"]
    g = graph.load(GRAPH)
    in_graph = {dossier.venue_key(k[1]) for k in g["kitchens"] if k[3] > 0}
    listed = set(g["raw"]["summary"]["starred"]["missing"])
    for r in cv:
        if not r.get("michelin"):
            continue
        keys = {dossier.venue_key(n) for n in
                (r.get("lineage_name"), r.get("star_name"), r.get("name")) if n}
        if keys & in_graph:
            continue
        # a star row with no node must be listed as missing under one of its
        # own name keys
        assert keys & listed, (r.get("name"), keys, listed)


def test_the_french_laundry_showpiece_figure_is_recounted():
    """The headline tree figure is proved by an independent breadth-first
    walk written here, not typed: reach, generations and starred count must
    equal tree()."""
    g = graph.load(GRAPH)
    root = graph._resolve(g, "The French Laundry")
    assert root is not None
    t = graph.tree(g, "french-laundry")
    # independent directed adjacency from the raw file: a hop a:b means a
    # move ran from a to b (or b to a); 'down' follows from -> to
    raw = _raw()
    adj = {}
    for pair, idxs in raw["hop_index"].items():
        for i in idxs:
            row = raw["moves"][i]
            adj.setdefault(row[1], set()).add(row[2])
    seen = {root}
    frontier = [root]
    gens = []
    for _ in range(3):
        nxt = []
        for x in frontier:
            for y in adj.get(x, ()):
                if y not in seen:
                    seen.add(y)
                    nxt.append(y)
        gens.append(len(nxt))
        frontier = nxt
    assert t["summary"]["reach"] == len(seen)
    assert t["summary"]["generations"] == gens
    starred = sum(1 for i in seen
                  if i != root and g["kitchens"][i][3] > 0)
    assert t["summary"]["starred"] == starred
