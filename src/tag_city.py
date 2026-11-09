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

# SF restaurants holding (or recently holding) one or more Michelin stars.
# Checked against the 2026 Michelin Guide (Wikipedia's starred-Bay-Area table,
# year columns 2019/2021-2026): dropped rows the guide shows unstarred and the
# permit data can't match (Bird Dog=Palo Alto, Sushi Jin/Iyasare/Wako/Helios/
# Sonsie/Selby's=no SF permit row, A Plume/Alcohol by Volume=unmatched,
# Aziza/Spruce/Tosca/Zuni/Rich Table=last starred years back), plus Verjus
# and Lord Stanley (no current star). Added current stars found missing:
# Birdsong (2-star), Californios (3-star), Kin Khao, Hilda and Jesse, Nisei,
# Naides, Acquerello, Lazy Bear.
STARRED = {"Benu", "Quince", "Saison", "Atelier Crenn", "Birdsong",
           "Rintaro", "Ariake", "Akiko's", "Kusakabe", "Marufuku Ramen", "Ju-ni",
           "7 Adams", "Angler", "Cotogna", "Delfina", "Mister Jiu's", "Nari",
           "State Bird Provisions", "The Progress", "Niku Steakhouse",
           "Flour + Water", "Kiln", "Luce", "Californios", "Kin Khao",
           "Hilda and Jesse", "Nisei", "Naides", "Acquerello", "Lazy Bear"}

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
    lineaged = {b["key"] for b in r["aggregations"]["to"]["buckets"] + r["aggregations"]["fr"]["buckets"] if b["key"]}
    ling_norm = {norm(v): v for v in lineaged}

    star_norm = {norm(s): s for s in STARRED}

    cv = json.load(open(CITY))["venues"]
    tagged = 0
    for v in cv:
        v.pop("lineaged", None); v.pop("michelin", None); v.pop("lineage_name", None)
        n = norm(v["name"])
        # exact, then token-prefix; honorific rows ("Restaurant Nisei") match
        # their bare graph name after the honorific is dropped
        hit = ling_norm.get(n)
        if not hit:
            for ln, orig in ling_norm.items():
                if token_prefix_match(n, ln) or \
                        (n.startswith("restaurant ") and n[len("restaurant "):] == ln):
                    hit = orig; break
        if hit:
            v["lineaged"] = True
            v["lineage_name"] = hit
            tagged += 1
        # michelin: exact, then prefix ("Quince" matches "Quince Restaurant",
        # "Angler" matches "Angler Sf, Llc"). Skip generic-prefix false positives
        # ("Chestnut" must not tag "Chestnut Diner" / "Chestnut Street …";
        # "Flour + Water" must not star the Pizza Shop / Pizzeria spin-offs —
        # only the flagship holds the star). star_name carries the curated
        # guide-list spelling through the flagship dedup below, so every
        # starred row (incl. permit oddities like "Angler Sf, Llc") has a
        # clean display name.
        GENERIC_STAR = {"chestnut", "akiko's", "flour + water"}
        # city names that carry a leading honorific the guide drops
        # ("Restaurant Naides" → Naides, "Restaurant Nisei" → Nisei)
        HONORIFIC = ("restaurant ",)
        for sn, orig in star_norm.items():
            matched = n == sn or (n.startswith(sn + " ") and sn not in GENERIC_STAR)
            if not matched and n.startswith(HONORIFIC) and n[len("restaurant "):] == sn:
                matched = True
            if matched:
                v["michelin"] = True
                v["star_name"] = orig
                v.setdefault("lineage_name", orig)
                break

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
                    r.pop("michelin", None); r.pop("star_name", None)

    # one starred name, several real branches (Akiko's: Nob Hill omakase +
    # Folsom St sushi; Saison: dining room 178 Townsend + cellar annex 234
    # Townsend): the guide stars the dining room, so annexes/branches keep
    # lineage but lose the star. Curated: starred address per star_name.
    STARRED_ADDR = {"Akiko's": "1501 CALIFORNIA ST",
                    "Saison": "178 TOWNSEND ST"}
    for sn, rows in by_star.items():
        want = STARRED_ADDR.get(sn)
        if want is None:
            continue
        for r in rows:
            if r.get("michelin") and r.get("address") != want:
                r.pop("michelin", None); r.pop("star_name", None)

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
