"""Tag ui/city_venues.json with lineaged/michelin flags.

Matching discipline: normalize both sides (case, punctuation, leading article),
then require an exact match or a full-token-prefix extension match ("Tartine"
matches "Tartine Bakery"). No raw substring matching — that's how "All Washed
Up" (a take-out) grabbed the lineage venue "All Washed Up (Washbag)".
"""
import json, re, os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src.cli import load_env
load_env(os.path.join(BASE, ".env"))
from src.es import make_client, INDEX
CITY = os.path.join(BASE, "ui", "city_venues.json")

# SF restaurants holding a Michelin star in the 2026 guide, with the star
# count. Verified against guide.michelin.com's San Francisco listing (all four
# pages) + each venue's distinction, cross-checked with Wikipedia's
# starred-Bay-Area table (2026 column). SF only — North/South Bay stars
# (SingleThread, French Laundry, Commis, Sonsie, ...) are outside the city
# dataset. Former stars removed from the old list: Rintaro (Bib Gourmand,
# not a star), Kusakabe (lost 2016), Ju-ni (lost 2021), Luce (lost 2018,
# closed), Cotogna / Flour + Water (Selected, never starred), Akiko's /
# Ariake / Delfina / Marufuku Ramen (never in the guide's starred tables).
# Added missing current SF stars: Sons & Daughters (2), Madcap, San Ho Won,
# Sorrel, Ssal, Wolfsbane (1).
STARRED = {"Benu": 3, "Quince": 3, "Californios": 3, "Atelier Crenn": 3,
           "Birdsong": 2, "Saison": 2, "Acquerello": 2, "Lazy Bear": 2,
           "Kiln": 2, "Sons & Daughters": 2,
           "7 Adams": 1, "Angler": 1, "Hilda and Jesse": 1, "Kin Khao": 1,
           "Madcap": 1, "Mister Jiu's": 1, "Nari": 1, "Naides": 1,
           "Niku Steakhouse": 1, "Nisei": 1, "San Ho Won": 1, "Sorrel": 1,
           "Ssal": 1, "State Bird Provisions": 1, "The Progress": 1,
           "Wolfsbane": 1}

def norm(s):
    s = s.lower()
    s = re.sub(r"[''`]", "'", s)
    s = re.sub(r"\b(the|a|an)\b", " ", s)
    s = re.sub(r"[^a-z0-9'+ ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def token_prefix_match(city_n, ling_n):
    """city venue name starts with the lineage name at a token boundary."""
    return city_n.startswith(ling_n + " ") or city_n == ling_n

def main():
    es = make_client()
    aggs = {"to": {"terms": {"field": "to_venue.keyword", "size": 65536}},
            "fr": {"terms": {"field": "from_venue.keyword", "size": 65536}}}
    r = es.search(index=INDEX, body={"size": 0, "aggs": aggs})
    # canonical graph name per normalization: several variants can share one
    # norm key ("Atwater Tavern" / "ATwater TAvern", "B. Patisserie" /
    # "b. patisserie", "LuLu" / "Lulu"), and set-iteration order would pick
    # stochastically. The variant carrying the most cited edges is the
    # citable one — it's also what /api/search resolves on.
    counts = {}
    for side in ("to", "fr"):
        for b in r["aggregations"][side]["buckets"]:
            k = b["key"]
            if k:
                counts[k] = counts.get(k, 0) + b["doc_count"]
    ling_norm = {}
    for name in counts:
        k = norm(name)
        if k not in ling_norm or counts[name] > counts[ling_norm[k]]:
            ling_norm[k] = name

    star_norm = {norm(s): s for s in STARRED}

    cv = json.load(open(CITY))["venues"]
    tagged = 0
    for v in cv:
        v.pop("lineaged", None); v.pop("michelin", None)
        v.pop("star_name", None); v.pop("stars", None); v.pop("lineage_name", None)
        n = norm(v["name"])
        # exact, then token-prefix; honorific rows ("Restaurant Nisei") match
        # their bare graph name after the honorific is dropped
        hit = ling_norm.get(n)
        if not hit:
            # longest prefix wins: ling_norm comes from a set (nondeterministic
            # order), and first-match lets a generic lineage ("The Kitchen" ->
            # "kitchen") consume a specific one ("Kitchen Story Cafe").
            best = None
            for ln, orig in ling_norm.items():
                if token_prefix_match(n, ln) or \
                        (n.startswith("restaurant ") and n[len("restaurant "):] == ln):
                    if best is None or len(ln) > len(best[0]):
                        best = (ln, orig)
            if best:
                hit = best[1]
        if hit:
            v["lineaged"] = True
            v["lineage_name"] = hit
            tagged += 1
        # michelin: exact, then prefix ("Quince" matches "Quince Restaurant",
        # "Angler" matches "Angler Sf, Llc"). star_name carries the curated
        # guide-list spelling through the flagship dedup below, so every
        # starred row (incl. permit oddities like "Angler Sf, Llc") has a
        # clean display name.
        # city names that carry a leading honorific the guide drops
        # ("Restaurant Naides" → Naides, "Restaurant Nisei" → Nisei)
        HONORIFIC = ("restaurant ",)
        # exact (incl. honorific) first — unambiguous — then longest prefix
        # wins, mirroring the lineage loop (star_norm is set-ordered).
        exact = None
        plen = 0; pstar = None
        for sn, orig in star_norm.items():
            if n == sn or (n.startswith(HONORIFIC) and n[len("restaurant "):] == sn):
                exact = orig; break
            if n.startswith(sn + " ") and len(sn) > plen:
                plen = len(sn); pstar = orig
        orig = exact or pstar
        if orig:
            v["michelin"] = True
            v["star_name"] = orig
            v["stars"] = STARRED[orig]
            v.setdefault("lineage_name", orig)

    # stars belong to the kitchen: where one starred name has both restaurant
    # permit rows and bar/tavern rows (Nisei's side-by-side H25+H86 permits,
    # Saison's cellar), the bar row keeps its star only when no restaurant
    # row carries it. Bar-only stars (a tavern that legitimately holds one)
    # survive.
    REST_PERMITS = ("H24", "H25", "H26", "H28", "H29")

    def is_rest_row(r):
        t = r.get("permit_type") or ""
        return t.startswith(REST_PERMITS)

    by_star = {}
    for v in cv:
        if v.get("michelin"):
            by_star.setdefault(v["star_name"], []).append(v)
    for sn, rows in by_star.items():
        if any(is_rest_row(r) for r in rows):
            for r in rows:
                if not is_rest_row(r):
                    r.pop("michelin", None); r.pop("star_name", None); r.pop("stars", None)

    # one starred name, several real branches (Saison: dining room 178
    # Townsend + cellar annex 234 Townsend): the guide stars the dining room,
    # so annexes/branches keep lineage but lose the star. Curated: starred
    # address per star_name.
    STARRED_ADDR = {"Saison": "178 TOWNSEND ST"}
    for sn, rows in by_star.items():
        want = STARRED_ADDR.get(sn)
        if want is None:
            continue
        for r in rows:
            if r.get("michelin") and r.get("address") != want:
                r.pop("michelin", None); r.pop("star_name", None); r.pop("stars", None)

    # one pin per lineage name: keep the row with the shortest name (the
    # flagship location), so Blue Bottle's 11 permits render as one dot
    best = {}
    for i, v in enumerate(cv):
        ln = v.get("lineage_name")
        if ln is None:
            continue
        if ln not in best or len(v["name"]) < len(cv[best[ln]]["name"]):
            best[ln] = i
    for i, v in enumerate(cv):
        if v.get("lineage_name") and best.get(v["lineage_name"]) != i:
            v.pop("lineaged", None); v.pop("lineage_name", None)

    json.dump({"venues": cv}, open(CITY, "w"), indent=0)
    mich = sum(1 for v in cv if v.get("michelin"))
    both = sum(1 for v in cv if v.get("michelin") and v.get("lineaged"))
    print(f"city venues: {len(cv)}  lineaged: {sum(1 for v in cv if v.get('lineaged'))}  michelin: {mich}  starred-and-lineaged: {both}")
    print("lineaged sample:", sorted({v["lineage_name"] for v in cv if v.get("lineaged")})[:15])

if __name__ == "__main__":
    main()
