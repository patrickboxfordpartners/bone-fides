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
    (parent-of, depth-of, order-of-discovery, adjacency) before any node cut."""
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
        if parent[i] is None:
            via, more = [], 0
        elif direction == "down":
            # the branch ran parent -> child
            via, more = _citations_for(g, parent[i], i)
        else:
            # an upstream branch cites the move that ran child -> parent
            via, more = _citations_for(g, i, parent[i])
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
    other_direction = max(0, len(other_order) - 1)
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
            "other_direction": other_direction,
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


def _chef_kitchens(g, pid):
    """Every kitchen in a chef's kept moves, with the move indices."""
    out = {}
    for i, row in enumerate(g["moves"]):
        if row[0] == pid:
            for k in (row[1], row[2]):
                if 0 <= k < len(g["kitchens"]):
                    out.setdefault(k, []).append(i)
    return out


def _resolve_end(g, name):
    """One end of a trace: a kitchen, or chef:<person id or name>."""
    if not name:
        return None, None
    if name.startswith("chef:"):
        q = name[5:].strip()
        hit = g["by_pid"].get(q)
        if hit is None:
            for p in g["people"]:
                if _fold(p[1]) == _fold(q):
                    hit = p
                    break
        if hit is None:
            return None, None
        return {"kind": "chef", "id": hit[0], "name": hit[1],
                "homonym": bool(hit[2])}, None
    i = _resolve(g, name)
    if i is None:
        return None, None
    k = g["kitchens"][i]
    also = None
    for p in g["people"]:
        if _fold(p[1]) == _fold(k[1]) or _fold(p[0]) == _fold(k[2]):
            also = {"kind": "chef", "id": p[0], "name": p[1]}
            break
    return {"kind": "kitchen", "id": k[0], "name": k[1], "slug": k[2],
            "stars": k[3]}, also


def _stint_row(g, pid, kitchen_i):
    """The row that joins a chef to one of their kitchens: their own cited
    move there (plan section 5: a chef end point's first or last row)."""
    row_k = g["kitchens"][kitchen_i]
    idxs = _chef_kitchens(g, pid).get(kitchen_i) or []
    cites = sorted(
        idxs,
        key=lambda i: (-(g["moves"][i][11] or 0),
                       -TIER_WEIGHT.get(g["moves"][i][5], 0),
                       0 if g["moves"][i][4] else 1,
                       g["moves"][i][6]))
    via = [_cite(g, i) for i in cites[:3]]
    return {"stint": True, "person": g["by_pid"][pid][1],
            "person_id": pid, "homonym": bool(g["by_pid"][pid][2]),
            "kitchen": {"id": row_k[0], "name": row_k[1], "stars": row_k[3]},
            "via": via, "more_via": max(0, len(cites) - 3)}


def connect(g, a, b):
    """The shortest chain of cited moves between two ends (plan section 5).

    Breadth-first on the undirected link set, neighbours in key order, so
    the same pair always returns the same chain. A chef end starts from
    every kitchen in that chef's kept moves; the row joining the chef to
    the chain is a stint row. `found: false` with the two connected-set
    sizes is the honest no-chain answer."""
    ea, also_a = _resolve_end(g, a)
    eb, _ = _resolve_end(g, b)
    if ea is None:
        return {"resolved": True, "found": False, "reason": "unknown_a",
                "query": a, "suggestions": unresolved(g, a)}
    if eb is None:
        return {"resolved": True, "found": False, "reason": "unknown_b",
                "query": b, "suggestions": unresolved(g, b)}
    if ea["kind"] == eb["kind"] and ea["id"] == eb["id"]:
        return {"resolved": True, "found": False, "reason": "same",
                "a": ea, "b": eb}

    def starts(end):
        if end["kind"] == "chef":
            return sorted(_chef_kitchens(g, end["id"]))
        return [_resolve(g, end["id"]) or _resolve(g, end.get("slug") or end["name"])]

    sa, sb = starts(ea), starts(eb)
    if any(s is None for s in sa + sb):
        return {"resolved": True, "found": False, "reason": "unknown_a"}
    # breadth-first from a's starts until a b start is reached
    parent = {}
    seen = set(sa)
    queue = list(sa)
    targets = set(sb)
    hit = None
    for s in queue:
        if s in targets:
            hit = s
            break
    while queue and hit is None:
        x = queue.pop(0)
        for y in sorted(g["und"].get(x, ())):
            if y in seen:
                continue
            seen.add(y)
            parent[y] = x
            if y in targets:
                hit = y
                queue = []
                break
            queue.append(y)
    if hit is None:
        def set_of(i):
            return g["comps"][g["comp"].get(i)] if g["comp"].get(i) is not None else 0
        return {"resolved": True, "found": False, "reason": "no_chain",
                "a": ea, "b": eb, "a_set": set_of(sa[0]) if sa else 0,
                "b_set": set_of(sb[0]) if sb else 0, "also": also_a}

    chain = [hit]
    cur = hit
    while cur in parent:
        cur = parent[cur]
        chain.append(cur)
    chain.reverse()

    hops = []
    for x, y in zip(chain, chain[1:]):
        row_x, row_y = g["kitchens"][x], g["kitchens"][y]
        via, more = _citations_for(g, x, y, limit=3)
        forward = bool(via)
        if not forward:
            via, more = _citations_for(g, y, x, limit=3)
        hops.append({
            "from": {"id": row_x[0], "name": row_x[1], "stars": row_x[3]},
            "to": {"id": row_y[0], "name": row_y[1], "stars": row_y[3]},
            "direction": "forward" if forward else "reverse",
            "via": via, "more_via": more})

    if ea["kind"] == "chef":
        hops.insert(0, _stint_row(g, ea["id"], chain[0]))
    if eb["kind"] == "chef":
        hops.append(_stint_row(g, eb["id"], chain[-1]))

    return {"resolved": True, "found": True, "length": len(chain) - 1,
            "a": ea, "b": eb, "hops": hops, "also": also_a,
            "built_at": g["raw"].get("built_at")}


def _kitchen_alumni(g, i):
    out = set()
    for tgts in g["out"].get(i, {}).values():
        for m in tgts:
            out.add(g["moves"][m][0])
    return out


def _tree_stats(g, i, depth=3):
    """reach, starred count and starred names within `depth` moves."""
    seen = {i}
    frontier = [i]
    starred_names = []
    for _ in range(depth):
        nxt = []
        for x in frontier:
            for y in sorted(g["out"].get(x, {})):
                if y in seen:
                    continue
                seen.add(y)
                nxt.append(y)
                if g["kitchens"][y][3] > 0:
                    starred_names.append(g["kitchens"][y][1])
        frontier = nxt
    starred_names.sort()
    return len(seen), len(starred_names), starred_names


def ledger(g):
    """The rankings payload (plan section 10). Memoized per graph file."""
    if g.get("_ledger") is not None:
        return g["_ledger"]

    alumni = {i: len(_kitchen_alumni(g, i)) for i in range(len(g["kitchens"]))}
    rows = []
    stats = {}
    for i, n in alumni.items():
        if n < 3:
            continue
        reach, starred, starred_names = _tree_stats(g, i)
        stats[i] = (reach, starred, starred_names)
        k = g["kitchens"][i]
        rows.append({"kitchen": {"id": k[0], "name": k[1], "slug": k[2],
                                 "stars": k[3]},
                     "alumni": n, "kitchens": reach, "reach": reach,
                     "starred": starred, "starred_names": starred_names})
    rows.sort(key=lambda r: (-r["alumni"], -r["reach"], r["kitchen"]["name"]))

    # leaders: the four record holders
    by_reach = sorted(rows, key=lambda r: (-r["reach"], -r["alumni"],
                                           r["kitchen"]["name"]))
    by_starred = sorted(rows, key=lambda r: (-r["starred"], -r["alumni"],
                                             r["kitchen"]["name"]))

    # mentors: chefs per named mentor, from the moves' mentor credit
    mentors = {}
    for i, row in enumerate(g["moves"]):
        m = row[8]
        if not m:
            continue
        slot = mentors.setdefault(m, {"chefs": set(), "moves": 0, "samples": []})
        slot["chefs"].add(row[0])
        slot["moves"] += 1
        if len(slot["samples"]) < 2:
            slot["samples"].append(i)
    mentor_rows = []
    for m, slot in mentors.items():
        if len(slot["chefs"]) < 2:
            continue
        mentor_rows.append({
            "mentor": m, "chefs": len(slot["chefs"]), "moves": slot["moves"],
            "sample": [_cite(g, i) for i in
                       sorted(slot["samples"],
                              key=lambda i2: -TIER_WEIGHT.get(g["moves"][i2][5], 0))[:2]]})
    mentor_rows.sort(key=lambda r: (-r["chefs"], -r["moves"], r["mentor"]))

    # starred rows: all Michelin kitchens, their cited arrivals
    starred_rows = []
    for i, k in enumerate(g["kitchens"]):
        if k[3] <= 0:
            continue
        arrivals = 0
        froms = []
        for a, tgts in g["out"].items():
            for b in tgts:
                if b == i:
                    arrivals += 1
                    froms.append(g["kitchens"][a][1])
        status = "linked" if g["degree"].get(i) else (
            "move_only" if alumni.get(i) else "none")
        starred_rows.append({
            "kitchen": {"id": k[0], "name": k[1], "slug": k[2], "stars": k[3]},
            "arrivals": arrivals, "from": sorted(set(froms))[:4],
            "alumni": alumni.get(i, 0), "status": status})
    for miss in g["raw"]["summary"]["starred"].get("missing_rows") or []:
        starred_rows.append({
            "kitchen": {"id": None, "name": miss["name"], "slug": None,
                        "stars": miss["stars"]},
            "arrivals": 0, "from": [], "alumni": 0, "status": "none"})
    starred_rows.sort(key=lambda r: (-r["arrivals"], r["kitchen"]["name"]))

    # featured: the tree with the most starred within three moves, and up to
    # four traceable pairs from the top kitchens by alumni
    featured_tree = by_starred[0]["kitchen"]["slug"] if by_starred else None
    pairs = []
    for r in rows[:12]:
        if r["kitchen"]["slug"] == featured_tree:
            continue
        if not r["starred_names"]:
            continue
        best = r["starred_names"][0]
        chain = connect(g, r["kitchen"]["slug"], best)
        if chain.get("found") and 2 <= chain["length"] <= 4:
            bi = _resolve(g, best)
            pairs.append({"a": r["kitchen"]["slug"],
                          "b": g["kitchens"][bi][2] if bi is not None else None,
                          "length": chain["length"]})
        if len(pairs) >= 4:
            break

    out = {
        "built_at": g["raw"].get("built_at"),
        "moves_on_display": g["raw"]["summary"]["gate_passed"],
        "featured": {"tree": featured_tree, "pairs": pairs},
        "leaders": {
            "alumni": {"slug": rows[0]["kitchen"]["slug"],
                       "name": rows[0]["kitchen"]["name"],
                       "value": rows[0]["alumni"]} if rows else {},
            "reach": {"slug": by_reach[0]["kitchen"]["slug"],
                      "name": by_reach[0]["kitchen"]["name"],
                      "value": by_reach[0]["reach"]} if by_reach else {},
            "starred_within": {"slug": by_starred[0]["kitchen"]["slug"],
                               "name": by_starred[0]["kitchen"]["name"],
                               "value": by_starred[0]["starred"]} if by_starred else {},
            "mentor": {"name": mentor_rows[0]["mentor"],
                       "value": mentor_rows[0]["chefs"]} if mentor_rows else {},
        },
        "kitchens": rows,
        "mentors": mentor_rows[:25],
        "starred": starred_rows,
        "rules": {"min_alumni": 3, "mentor_min_chefs": 2, "depth": 3,
                  "mentor_moves": g["raw"]["summary"]["mentor_moves"]},
    }
    g["_ledger"] = out
    return out
