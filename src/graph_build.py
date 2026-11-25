"""Build the committed graph file (docs/flagship/plan.md sections 2-4).

A pure function: edges in, dict out. It imports the gate, the identity
clustering and the venue keys from src.dossier so the graph, the dossiers
and the stats cannot drift apart. It is NOT shipped to the Vercel function;
scripts/build_graph.py calls it at corpus-update time and commits the result
to ui/graph.json, which the function reads through dossier.data_path().

What the builder keeps, per plan section 2:
  - the move passes the display gate (citation_reason is truthy);
  - the person is named (not a collective, not "a chef", not "alums");
  - every venue is a named kitchen (not a description, not a show);
  - for a hop (both venues present): the two venues have different keys,
    also after parentheticals are removed (no same-brand relocations).
One hop is one named person, one quotation and one source link.
"""
import re
import unicodedata

from . import dossier


# Bay Area towns outside San Francisco (plan section 11). "Richmond" is not
# in the list: it is also a San Francisco district.
BAY_AREA_TOWNS = (
    "alameda", "albany", "berkeley", "burlingame", "campbell", "castro valley",
    "cupertino", "daly city", "danville", "dublin", "fremont", "hayward",
    "lafayette", "los gatos", "mill valley", "moraga", "mountain view",
    "napa", "oakland", "palo alto", "petaluma", "redwood city", "rutherford",
    "san bruno", "san carlos", "san jose", "san mateo", "santa rosa",
    "sausalito", "sonoma", "st helena", "walnut creek", "woodside",
    "yountville",
)

BAY_AREA_ANCHORS = (
    ("The French Laundry", "Yountville"),
    ("Chez Panisse", "Berkeley"),
    ("Manresa", "Los Gatos"),
)


def _slug(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s


def _star_rows(starred_rows):
    """Michelin rows, each with the keys its names fold to. The join goes
    through venue_key(lineage_name) and venue_key(star_name) — the guide says
    "Naides", the record says "Restaurant Naides"."""
    out = []
    for r in starred_rows or []:
        if not r.get("michelin"):
            continue
        names = [n for n in (r.get("star_name"), r.get("lineage_name"),
                             r.get("name")) if n]
        keys = {dossier.venue_key(n) for n in names}
        out.append({"keys": keys, "stars": int(r.get("stars") or 1),
                    "name": names[0]})
    return out


def build(edges, starred_rows=None, alias_data=None, hood_maps=None):
    """Edges (the full corpus) -> the graph dict written to ui/graph.json."""
    star_rows = _star_rows(starred_rows)

    # ---- pass 1: keep moves (gate, named person, named kitchen) ----
    dropped = {"gate": 0, "unnamed_person": 0, "unnamed_kitchen": 0,
               "junk_kitchen": 0, "same_brand": 0}
    kept = []
    for e in edges:
        if not dossier.citation_reason(e):
            dropped["gate"] += 1
            continue
        if not dossier._is_named_person(e.get("person")) \
                or dossier._is_collective(e.get("person")):
            dropped["unnamed_person"] += 1
            continue
        vs = []
        bad = False
        for v in (e.get("from_venue"), e.get("to_venue")):
            if not v:
                continue
            if dossier._is_junk_venue(v):
                dropped["junk_kitchen"] += 1
                bad = True
                break
            if not dossier.is_named_kitchen(v):
                dropped["unnamed_kitchen"] += 1
                bad = True
                break
        if bad:
            continue
        kept.append(e)

    # ---- pass 2: person identity (one clustering over all kept moves) ----
    # identity() returns the public cluster shape: name (most-cited variant),
    # aliases, homonym, n, edges. The person id is a slug of the cluster's
    # normalized name key; a key with several clusters gets ~2, ~3 in move
    # order, and the two clusters stay separate people.
    clusters = dossier.identity(kept)
    people_rows = []
    person_index = {}
    seen = {}
    for c in clusters:
        pid = _slug(dossier.norm_name(c["name"]))
        seen[pid] = seen.get(pid, 0) + 1
        if seen[pid] > 1:
            pid = f"{pid}~{seen[pid]}"
        people_rows.append([pid, c["name"], bool(c.get("homonym"))])
        for e in c["edges"]:
            person_index[id(e)] = pid

    # ---- pass 3: kitchen nodes ----
    # spellings keyed by venue_key, with citation counts for the display name
    spell = {}
    for e in kept:
        for v in (e.get("from_venue"), e.get("to_venue")):
            if not v:
                continue
            k = dossier.venue_key(v)
            if k:
                spell.setdefault(k, {}).setdefault(v, 0)
                spell[k][v] += 1
    merge_table = (alias_data or {}).get("merge") or {}
    canonical = {}
    for title, variants in merge_table.items():
        for v in list(variants) + [title]:
            canonical[dossier.venue_key(v)] = title
    # a starred kitchen shows the star list's name (the guide's own title)
    star_fallback = {}
    for r in star_rows:
        for k in r["keys"]:
            star_fallback.setdefault(k, r["name"])

    def display_name(key):
        if key in canonical:
            return canonical[key]
        if key in star_fallback:
            return star_fallback[key]
        ranked = sorted(spell.get(key, {}).items(),
                        key=lambda kv: (-kv[1], kv[0]))
        if not ranked:
            return key
        # the display name must itself be a named kitchen
        named = [(v, c) for v, c in ranked if dossier.is_named_kitchen(v)]
        if named:
            ranked = named
        name = ranked[0][0]
        stripped = re.sub(r"\s*\([^)]*\d[^)]*\)\s*$", "", name).strip()
        # the display name must fold back to the node's own key AND stay a
        # named kitchen; otherwise keep the spelling as extracted
        if stripped and dossier.is_named_kitchen(stripped) \
                and dossier.venue_key(stripped) == key:
            return stripped
        return name

    kitchens = []
    kindex = {}
    for key in sorted(spell):
        name = display_name(key)
        slug = _slug(name)
        if dossier.venue_key(slug) != key:
            slug = key
        others = sorted(v for v in spell[key] if v != name)
        kindex[key] = len(kitchens)
        kitchens.append([key, name, slug, 0, others])
    # stars: a starred row joins the first of its name keys that is a node
    star_name = {}
    for r in star_rows:
        for key in r["keys"]:
            if key in kindex:
                i = kindex[key]
                kitchens[i][3] = max(kitchens[i][3], r["stars"])
                star_name.setdefault(key, kitchens[i][1])
                break

    def vkey(v):
        return dossier.venue_key(v)

    def bare(v):
        return dossier.venue_key(re.sub(r"\([^)]*\)", " ", v or ""))

    # ---- pass 4: move rows and hops ----
    hops = {}
    moves = []
    mentor_moves = 0
    for e in kept:
        p = person_index.get(id(e))
        if p is None:  # identity dropped a cluster edge we did not keep
            continue
        fv, tv = e.get("from_venue"), e.get("to_venue")
        fk = vkey(fv) if fv else None
        tk = vkey(tv) if tv else None
        fi = kindex.get(fk, -1) if fk else -1
        ti = kindex.get(tk, -1) if tk else -1
        ev = e.get("evidence") or ""
        quote_score = 0
        if fi >= 0 and ti >= 0:
            qw = dossier._quote_words(ev)
            quote_score = ((1 if dossier._words_name_venue(qw, (fv,)) else 0)
                           + (1 if dossier._words_name_venue(qw, (tv,)) else 0))
        mentor = e.get("mentor")
        if mentor and mentor.lower() not in ("null", "none"):
            surname = mentor.split()[-1].lower()
            if surname and surname in set(dossier._quote_words(ev)):
                mentor_moves += 1
            else:
                mentor = None
        row = [p, fi, ti, e.get("role") or "", e.get("year"),
               dossier.outlet_tier(e.get("source"), e.get("source_url")),
               e.get("source_url") or "", ev, mentor or None,
               e.get("confidence"), (e.get("action") or ""), quote_score,
               dossier.citation_reason(e)]
        moves.append(row)
        if fi >= 0 and ti >= 0 and fi != ti:
            # same-brand rule: one kitchen, parentheticals aside
            if fv and tv and bare(fv) and bare(fv) == bare(tv):
                dropped["same_brand"] += 1
                continue
            pair = (min(fi, ti), max(fi, ti))
            hops.setdefault(pair, []).append(len(moves) - 1)

    # ---- pass 5: link sets and connected sets ----
    undirected = {}
    for (a, b) in hops:
        undirected.setdefault(a, set()).add(b)
        undirected.setdefault(b, set()).add(a)
    comp_id = {}
    comps = []
    for start in sorted(undirected):
        if start in comp_id:
            continue
        cid = len(comps)
        stack, nodes = [start], []
        comp_id[start] = cid
        while stack:
            n = stack.pop()
            nodes.append(n)
            for m in undirected.get(n, ()):
                if m not in comp_id:
                    comp_id[m] = cid
                    stack.append(m)
        comps.append(nodes)

    # ---- pass 6: Bay Area figures ----
    ba_moves = 0
    town_counts = {}
    for row in moves:
        text = " ".join(dossier._quote_words(row[7]))
        hit = False
        for town in BAY_AREA_TOWNS:
            if re.search(r"\b" + re.escape(town) + r"\b", text):
                town_counts[town] = town_counts.get(town, 0) + 1
                hit = True
        if hit:
            ba_moves += 1
    towns = [[town.title() if " " in town else town.capitalize(), n]
             for town, n in sorted(town_counts.items())]
    kitchens_placed_sf = 0
    anchors = []
    for name, town in BAY_AREA_ANCHORS:
        key = dossier.venue_key(name)
        if key not in kindex:
            continue
        ki = kindex[key]
        n = 0
        quotes_naming = 0
        for row in moves:
            if row[1] == ki or row[2] == ki:
                n += 1
                text = " ".join(dossier._quote_words(row[7]))
                if re.search(r"\b" + re.escape(town.lower()) + r"\b", text):
                    quotes_naming += 1
        if quotes_naming >= 1:
            anchors.append({"name": name, "slug": kitchens[ki][2],
                            "town": town, "moves": n,
                            "quotes_naming_town": quotes_naming})

    # ---- pass 7: star summary ----
    linked = set()
    for (a, b) in hops:
        linked.add(a)
        linked.add(b)
    matched_rows = sum(1 for r in star_rows
                       if any(k in kindex for k in r["keys"]))
    missing_rows = [r for r in star_rows
                    if not any(k in kindex for k in r["keys"])]
    missing = sorted(sorted(r["keys"])[0] for r in missing_rows)

    largest = max((len(c) for c in comps), default=0)

    if hood_maps:
        from .hoods import hood_for
        for i in linked:
            if hood_for(kitchens[i][1], hood_maps):
                kitchens_placed_sf += 1

    return {
        "v": 1,
        "built_at": "",  # scripts/build_graph.py stamps this
        "summary": {
            "source_moves": len(edges),
            "gate_passed": sum(1 for e in edges if dossier.citation_reason(e)),
            "moves_kept": len(moves),
            "hops": sum(len(v) for v in hops.values()),
            "kitchens_linked": len(linked),
            "largest_set": largest,
            "people": len(people_rows),
            "homonym_flags": sum(1 for p in people_rows if p[2]),
            "mentor_moves": mentor_moves,
            "moves_with_year": sum(1 for row in moves if row[4]),
            "published_at": sum(1 for e in edges if e.get("published_at")),
            "dropped": dropped,
            "starred": {
                "source": "Michelin Guide 2026, San Francisco",
                "total": len(star_rows),
                "with_move": matched_rows,
                "linked": matched_rows,
                "missing": missing,
            },
            "bay_area": {
                "moves": ba_moves,
                "towns": towns,
                "kitchens_placed_sf": kitchens_placed_sf,
                "anchors": anchors,
            },
        },
        "kitchens": kitchens,
        "people": people_rows,
        "moves": moves,
        "hop_index": {f"{a}:{b}": sorted(v) for (a, b), v in sorted(hops.items())},
    }
