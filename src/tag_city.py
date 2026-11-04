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

# SF restaurants holding (or recently holding) one or more Michelin stars
STARRED = {"Benu", "Quince", "Saison", "Atelier Crenn", "Bird Dog", "Sushi Jin", "Iyasare",
           "Rintaro", "Ariake", "Akiko's", "Spruce", "Kusakabe", "Marufuku Ramen", "Ju-ni",
           "Wako", "Estiatorio Ornos", "Aziza", "Chestnut", "Helios", "7 Adams", "A Plume",
           "Alcohol by Volume", "Angler", "Cotogna", "Delfina", "Mister Jiu's", "Nari",
           "Rich Table", "State Bird Provisions", "The Progress", "Tosca Cafe", "Verjus",
           "Zuni Cafe", "Jardenea", "Leo's Oyster Bar", "Lord Stanley", "Niku Steakhouse",
           "Flour + Water", "Sonsie", "Kiln", "Selby's", "Luce"}

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
        # exact, then token-prefix
        hit = ling_norm.get(n)
        if not hit:
            for ln, orig in ling_norm.items():
                if token_prefix_match(n, ln):
                    hit = orig; break
        if hit:
            v["lineaged"] = True
            v["lineage_name"] = hit
            tagged += 1
        # michelin: exact, then prefix ("Quince" matches "Quince Restaurant",
        # "Angler" matches "Angler Sf, Llc"). Skip generic-prefix false positives
        # ("Chestnut" must not tag "Chestnut Diner" / "Chestnut Street …").
        GENERIC_STAR = {"chestnut", "akiko's"}
        for sn, orig in star_norm.items():
            if n == sn or (n.startswith(sn + " ") and sn not in GENERIC_STAR):
                v["michelin"] = True
                v.setdefault("lineage_name", orig)
                break

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
