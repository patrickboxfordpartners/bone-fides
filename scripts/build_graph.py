"""Build ui/graph.json, the committed graph file the showpiece views read.

Reads every move from Elasticsearch (search_after pages of 5,000 — two
requests today), runs src.graph_build.build() and writes the file through a
temporary rename so a failed run cannot leave a half-written graph behind.

The file is COMMITTED and ships in the function bundle, so a deploy never
depends on Elasticsearch and the local demo and the deploy show the same
graph. Re-run after each corpus update (after the gate, if it changed):

    .venv/bin/python scripts/build_graph.py

    .venv/bin/python scripts/build_graph.py --check
        rebuild in memory and compare with the committed file, ignoring
        built_at; exit code 1 means the file is stale.

It follows the pattern of scripts/stamp_score_sample.py.
"""
import argparse
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src.cli import load_env  # noqa: E402

load_env(os.path.join(BASE, ".env"))

OUT = os.path.join(BASE, "ui", "graph.json")
INDEX = "bone-fides-edges"


def load_edges():
    from src.es import make_client
    es = make_client()
    out, after = [], None
    while True:
        body = {"size": 5000, "query": {"match_all": {}}, "sort": [{"_doc": "asc"}]}
        if after is not None:
            body["search_after"] = after
        page = es.search(index=INDEX, body=body)["hits"]["hits"]
        if not page:
            break
        out.extend(h["_source"] for h in page)
        after = page[-1]["sort"]
    return out


def build_graph(edges):
    from src import graph_build
    with open(os.path.join(BASE, "ui", "venue_aliases.json"), encoding="utf-8") as f:
        alias_data = json.load(f)
    with open(os.path.join(BASE, "ui", "city_venues.json"), encoding="utf-8") as f:
        starred_rows = json.load(f)["venues"]
    try:
        from src.hoods import load_hood_maps
        hood_maps = load_hood_maps()
    except Exception:
        hood_maps = None
    g = graph_build.build(edges, starred_rows=starred_rows,
                          alias_data=alias_data, hood_maps=hood_maps)
    g["built_at"] = datetime.date.today().isoformat()
    return g


def write_identity_review(g, path):
    """Candidate identity groups (plan section 3): venue spellings that
    differ only by a parenthetical note, with the node key each spelling
    resolves to today, so the owner's rulings can be re-checked after each
    corpus update."""
    import re as _re
    from src import dossier as _D
    groups = {}
    for key, name, slug, stars, others in g["kitchens"]:
        for spelling in [name] + list(others):
            base = _re.sub(r"\s*\([^)]*\)\s*$", "", spelling).strip()
            if not base or base == spelling:
                continue
            groups.setdefault(_D.venue_key(base), []).append(
                {"spelling": spelling, "key": key})
    out = []
    for base_key, rows in sorted(groups.items()):
        keys = sorted({r["key"] for r in rows})
        out.append({"base_key": base_key,
                    "same_node": len(keys) == 1,
                    "spellings": sorted(r["spelling"] for r in rows)})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    return len(out)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true",
                   help="rebuild in memory and compare with the committed file")
    p.add_argument("--edges", help="cached edges file instead of Elasticsearch")
    a = p.parse_args(argv)

    if a.edges:
        with open(a.edges, encoding="utf-8") as f:
            edges = json.load(f)
    else:
        edges = load_edges()
    print(f"loaded {len(edges)} moves")
    g = build_graph(edges)

    s = g["summary"]
    print(f"kept {s['moves_kept']} moves, {s['hops']} hops, "
          f"{s['kitchens_linked']} linked kitchens "
          f"(largest set {s['largest_set']}), {s['people']} people")

    if a.check:
        with open(OUT, encoding="utf-8") as f:
            committed = json.load(f)
        fresh = {k: v for k, v in g.items() if k != "built_at"}
        old = {k: v for k, v in committed.items() if k != "built_at"}
        if fresh == old:
            print("ok: ui/graph.json is up to date")
            return 0
        print("STALE: ui/graph.json differs from a fresh build")
        return 1

    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, OUT)
    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")
    n_groups = write_identity_review(g, os.path.join(BASE, "crawl",
                                                      "graph_identity_review.json"))
    print(f"wrote crawl/graph_identity_review.json ({n_groups} candidate groups)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
