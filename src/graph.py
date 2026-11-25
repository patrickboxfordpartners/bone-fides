"""Graph reads for the Tree view (docs/flagship/plan.md section 5).

Stdlib only. It imports nothing from src.dossier: the Vercel function ships
this file beside ui/graph.json and venue_aliases.py, and the graph endpoints
must never pull the Elasticsearch client into memory. dossier.py imports THIS
module and loads the file with data_path("graph.json"), so build.sh ships
both and tests/test_shared_core.py keeps the two runtimes honest.

The file is built offline by scripts/build_graph.py and committed; every
figure the views show comes from it, so the local demo and the deploy show
the same graph even when Elasticsearch is down.
"""
import json
import re
import unicodedata

from .venue_aliases import identity as _venue_key

# Outlet citation weight, twin of dossier.TIER_WEIGHT (roles.py and eras.py
# hold the same kind of twin). Order citations by it when a hop has several.
TIER_WEIGHT = {"sfchronicle": 12, "sfgate": 8, "eater": 6}

MAX_NODES = 300          # the tree cut; totals are computed before the cut
MAX_DEPTH = 3
MAX_VIA = 2              # citations per branch in the payload
EVIDENCE_MAX = 220       # responses cut the quotation, as assemble_dossier does

_LOADED = {}


def _fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def load(path):
    """Parse the graph file once for each warm instance and index it:
    out-links, in-links, an undirected link set, connected-set ids, and name
    indexes for the kitchen picker."""
    key = str(path)
    g = _LOADED.get(key)
    if g is not None:
        return g
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    kitchens = raw["kitchens"]
    people = raw["people"]
    moves = raw["moves"]
    out, und, hop_moves = {}, {}, {}
    for pair, idxs in (raw.get("hop_index") or {}).items():
        a, b = pair.split(":", 1)
        a, b = int(a), int(b)
        hop_moves[(a, b)] = idxs
        # direction of each move row: row[1]=from, row[2]=to
        for i in idxs:
            row = moves[i]
            if row[1] == a and row[2] == b:
                out.setdefault(a, {})[b] = out.get(a, {}).get(b, []) + [i]
            else:
                out.setdefault(b, {})[a] = out.get(b, {}).get(a, []) + [i]
    for a, tgt in out.items():
        for b in tgt:
            und.setdefault(a, set()).add(b)
            und.setdefault(b, set()).add(a)
    comp = {}
    comps = []
    for start in sorted(und):
        if start in comp:
            continue
        cid = len(comps)
        stack = [start]
        comp[start] = cid
        n = 0
        while stack:
            x = stack.pop()
            n += 1
            for y in und.get(x, ()):
                if y not in comp:
                    comp[y] = cid
                    stack.append(y)
        comps.append(n)
    kname = {}
    for i, k in enumerate(kitchens):
        kname.setdefault(_fold(k[1]), i)
        kname.setdefault(_fold(k[2]), i)
        kname.setdefault(_fold(k[0]), i)
    kslug = {k[2]: i for i, k in enumerate(kitchens)}
    kkey = {k[0]: i for i, k in enumerate(kitchens)}
    by_pid = {p[0]: p for p in people}
    pname = {}
    for i, p in enumerate(people):
        pname.setdefault(_fold(p[1]), i)
        pname.setdefault(_fold(p[0]), i)
    g = {
        "raw": raw,
        "kitchens": kitchens, "people": people, "moves": moves,
        "out": out, "und": und, "comp": comp, "comps": comps,
        "hop_moves": hop_moves, "kname": kname, "kslug": kslug,
        "pname": pname, "by_pid": by_pid, "kkey": kkey,
        "degree": {i: len(und.get(i, ())) for i in range(len(kitchens))},
    }
    _LOADED[key] = g
    return g


def _resolve(g, name):
    """A kitchen by display name, slug, venue key or any alias spelling —
    the same identity rule the dossiers use, so 'The French Laundry',
    'french-laundry' and 'French Laundry' are one kitchen."""
    if not name:
        return None
    n = _fold(name)
    hit = g["kname"].get(n)
    if hit is None:
        hit = g["kslug"].get(name)
    if hit is None:
        hit = g["kkey"].get(_venue_key(name))
    if hit is None and n.startswith("the "):
        hit = g["kname"].get(n[4:])
    return hit


def _cite(g, i):
    """One citation dict from a move row, quotation cut to 220 characters."""
    row = g["moves"][i]
    p = g["by_pid"].get(row[0], [row[0], row[0], False])
    return {
        "person": p[1], "person_id": p[0], "homonym": bool(p[2]),
        "role": row[3], "year": row[4], "outlet": row[5],
        "confidence": row[9],
        "source_url": row[6] if str(row[6]).startswith(("http://", "https://")) else None,
        "evidence": (row[7] or "")[:EVIDENCE_MAX],
    }


def _citations_for(g, a, b, limit=MAX_VIA):
    """The best citations for a hop, in the plan's order: quote names both
    kitchens, then one; then outlet weight; then a move with a year; then the
    source URL as the stable tie-break.

    Only moves that ran from `a` to `b` are candidates: a branch that says
    'where the parent's alumni went' must not cite someone who moved the
    other way."""
    idxs = []
    for pair in ((a, b), (b, a)):
        for i in g["hop_moves"].get(pair) or ():
            row = g["moves"][i]
            if (row[1], row[2]) == (a, b):
                idxs.append(i)
    ranked = sorted(
        idxs,
        key=lambda i: (-(g["moves"][i][11] or 0),
                       -TIER_WEIGHT.get(g["moves"][i][5], 0),
                       0 if g["moves"][i][4] else 1,
                       g["moves"][i][6]))
    return [_cite(g, i) for i in ranked[:limit]], max(0, len(ranked) - limit)


def _walk(g, root, depth, direction):
    """Breadth-first tree over the hops. Each kitchen appears once, at its
    smallest depth; the parent is the first one in key order. Returns
    (parent-of, depth-of, order-of-discovery) before any node cut."""
    adj = g["out"] if direction == "down" else {}
    if direction != "down":
        adj = {}
        for a, tgts in g["out"].items():
            for b in tgts:
                adj.setdefault(b, {})[a] = tgts[b]
    parent = {root: None}
    d = {root: 0}
    order = [root]
    frontier = [root]
    for step in range(1, depth + 1):
        nxt = []
        for x in frontier:
            for y in sorted(adj.get(x, {})):
                if y in d:
                    continue
                d[y] = step
                parent[y] = x
                nxt.append(y)
                order.append(y)
        frontier = nxt
    return parent, d, order, adj


def _knode(g, i):
    k = g["kitchens"][i]
    return {"id": k[0], "name": k[1], "slug": k[2], "stars": k[3]}


def tree(g, name, depth=MAX_DEPTH, direction="down", booking=None):
    """The family tree of one kitchen. direction 'down' follows hops out of
    the kitchen (where its alumni went); 'up' follows hops in reverse (where
    its people came from)."""
    root = _resolve(g, name)
    if root is None:
        return None
    depth = max(1, min(int(depth or MAX_DEPTH), MAX_DEPTH))
    parent, dist, order, adj = _walk(g, root, depth, direction)
    generations = [0] * depth
    for i in order[1:]:
        generations[dist[i] - 1] += 1
    reach = len(order)
    truncated = reach > MAX_NODES
    kept = order[:MAX_NODES]
    kept_set = set(kept)

    below = {}
    for i in reversed(kept):
        p = parent[i]
        if p is not None:
            below[p] = below.get(p, 0) + 1 + below.get(i, 0)

    def node(i):
        n = _knode(g, i)
        n["gen"] = dist[i]
        n["below"] = below.get(i, 0)
        if booking:
            n["booking"] = booking(g["kitchens"][i][1])
        else:
            n["booking"] = None
        via, more = _citations_for(g, parent[i], i) if parent[i] is not None else ([], 0)
        n["via"] = via
        n["more_via"] = more
        return n

    kids = {}
    for i in kept:
        p = parent[i]
        if p is not None:
            kids.setdefault(p, []).append(i)

    def build(i):
        n = node(i)
        n["children"] = [build(c) for c in
                         _sort_indexes(kids.get(i, []))]
        return n

    def _sort_indexes(idxs):
        rows = []
        for c in idxs:
            k = g["kitchens"][c]
            rows.append((c, {"stars": k[3], "below": below.get(c, 0), "name": k[1]}))
        rows.sort(key=lambda r: (-r[1]["stars"], -r[1]["below"], r[1]["name"]))
        return [c for c, _ in rows]

    children = [build(c) for c in _sort_indexes(kids.get(root, []))]

    starred_names = []
    for i in order:                      # before the cut: totals stay whole
        if g["kitchens"][i][3] > 0 and i != root:
            starred_names.append(g["kitchens"][i][1])
    starred_names.sort()

    # alumni: distinct people on the hops OUT of the kitchen
    alumni = set()
    for tgts in g["out"].get(root, {}).values():
        for i in tgts:
            alumni.add(g["moves"][i][0])

    _, _, other_order, _ = _walk(g, root, depth,
                                 "up" if direction == "down" else "down")
    k = _knode(g, root)
    if booking:
        k["booking"] = booking(g["kitchens"][root][1])
    else:
        k["booking"] = None
    s = g["raw"]["summary"]
    return {
        "resolved": True,
        "direction": direction,
        "built_at": g["raw"].get("built_at"),
        "corpus": {"moves_displayed": s.get("moves_kept"),
                   "moves_with_year": s.get("moves_with_year")},
        "root": k,
        "summary": {
            "alumni": len(alumni),
            "generations": generations,
            "reach": reach,
            "starred": len(starred_names),
            "starred_names": starred_names,
            "depth": depth,
            "truncated": truncated,
            "other_direction": len(other_order),
        },
        "children": children,
    }


def unresolved(g, query, limit=6):
    """Suggestions for a name the graph does not know (as /api/search does)."""
    q = _fold(query)
    if not q:
        return []
    seen, out = set(), []
    for name, i in sorted(g["kname"].items()):
        if i in seen:
            continue
        if q in name or name.startswith(q):
            seen.add(i)
            k = g["kitchens"][i]
            out.append({"kind": "kitchen", "id": k[0], "name": k[1],
                        "slug": k[2], "stars": k[3]})
        if len(out) >= limit:
            break
    return out


def nodes(g, q, kind="any", limit=8, near=None):
    """Kitchen and chef suggestions on folded word prefixes, ordered by match
    quality then hop count. `joined` is present when `near` is set: true when
    the two nodes share a connected set."""
    q = _fold(q)
    if len(q) < 2 or not q:
        return []
    limit = max(1, min(int(limit or 8), 12))
    out = []
    if kind in ("kitchen", "any"):
        for i, k in enumerate(g["kitchens"]):
            name = _fold(k[1])
            if name == q or name.startswith(q) or (" " + q) in name or \
                    any(w.startswith(q) for w in name.split()):
                n = {"kind": "kitchen", "id": k[0], "name": k[1], "slug": k[2],
                     "stars": k[3], "hops": g["degree"].get(i, 0),
                     "has_tree": g["degree"].get(i, 0) > 0, "note": None}
                if near is not None and g["comp"]:
                    n["joined"] = g["comp"].get(i) == g["comp"].get(near)
                out.append(n)
    if kind in ("chef", "any"):
        for p in g["people"]:
            name = _fold(p[1])
            if name == q or name.startswith(q) or (" " + q) in name or \
                    any(w.startswith(q) for w in name.split()):
                ks = []
                for row in g["moves"]:
                    if row[0] == p[0]:
                        for fi in (row[1], row[2]):
                            if 0 <= fi < len(g["kitchens"]):
                                nm = g["kitchens"][fi][1]
                                if nm not in ks:
                                    ks.append(nm)
                            if len(ks) >= 2:
                                break
                    if len(ks) >= 2:
                        break
                out.append({"kind": "chef", "id": p[0], "name": p[1],
                            "hops": 0, "has_tree": False,
                            "note": ", ".join(ks) or None})
    out.sort(key=lambda n: (0 if n["kind"] == "kitchen" else 1, -n["hops"], n["name"]))
    return out[:limit]


def summary(g):
    """The file's own summary, with the build date. Memoized by load()."""
    s = dict(g["raw"]["summary"])
    s["built_at"] = g["raw"].get("built_at")
    return s
