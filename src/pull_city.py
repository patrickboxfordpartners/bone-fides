"""Pull every permitted food business (SF DPH inspections dataset tvy3-wexg)
into ui/city_venues.json — the "universe" layer for the map.

One row per permit (dedup by permit_number), keep only rows with lat/lng.
Restaurants (H24 - RESTAURANT...) are the headline class; bars/bakeries/cafes
also included — everything permitted that serves food/drink.
"""
import json, os, collections, re, requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "ui", "city_venues.json")
URL = "https://data.sf.gov/resource/tvy3-wexg.json"

def fetch_all():
    rows, offset = [], 0
    while True:
        params = {"$limit": 5000, "$offset": offset,
                  "$select": "permit_number, dba, permit_type, street_address, "
                             "latitude, longitude, point, analysis_neighborhood",
                  "$order": "permit_number"}
        with requests.get(URL, params=params, timeout=60) as r:
            r.raise_for_status()
            batch = r.json()
        rows.extend(batch)
        print(f"  offset {offset}: +{len(batch)} (total {len(rows)})")
        if len(batch) < 5000:
            break
        offset += 5000
    return rows

def main():
    rows = fetch_all()
    by_permit = {}
    for r in rows:
        p = r.get("permit_number")
        if not p or not r.get("latitude") or not r.get("dba"):
            continue
        # first-seen wins; inspect dataset rows are inspection events
        by_permit.setdefault(p, r)
    venues = []
    for p, r in by_permit.items():
        try:
            lat, lng = float(r["latitude"]), float(r["longitude"])
        except (TypeError, ValueError):
            continue
        if not (37.6 < lat < 37.85 and -123.05 < lng < -122.3):
            continue
        name = (r.get("dba") or "").strip().title().replace(" 'S", "'S")
        # .title() capitalizes after any non-letter, so possessives come out
        # "Akiko'S"/"Peet'S" — a possessive-final S is lower case ("Akiko's").
        # Only the trailing apostrophe-S is touched; "O'Shea" keeps its cap.
        # ("It'Sugar"/"Chef'Store" brand stylings are re-cased back on next
        # re-pull; they're curated here because the raw DBA is all-caps.)
        name = re.sub(r"(?<=[A-Za-z])'S\b", "'s", name)
        name = name.replace("''", "'")  # raw typos like "Sammy''S On 2Nd"
        name = re.sub(r"(?<=[A-Za-z])'S\b", "'s", name)
        if not name or name.lower().startswith(("none", "unknown", "test")):
            continue
        venues.append({
            "name": name,
            "permit_type": r.get("permit_type") or "",
            "address": (r.get("street_address") or "").strip(),
            "neighborhood": r.get("analysis_neighborhood") or "",
            "lat": lat, "lng": lng,
        })
    # dedup by (name, address)
    seen, uniq = set(), []
    for v in venues:
        k = (v["name"].lower(), v["address"].lower())
        if k in seen: continue
        seen.add(k); uniq.append(v)
    # Two Michelin-starred kitchens have no permit row in the DPH dataset
    # (Madcap: 3★-adjacent, 2026 guide lists it; San Ho Won: 1★): the DBA
    # never got filed/recorded. Curated additions so the star roster doesn't
    # silently drop real starred restaurants.
    uniq += [
        {"name": "Madcap", "permit_type": "H26 - RESTAURANT OVER 2,000 SQFT",
         "address": "3195 California St", "neighborhood": "Presidio Heights",
         "lat": 37.7872056, "lng": -122.4465788},
        {"name": "San Ho Won", "permit_type": "H26 - RESTAURANT OVER 2,000 SQFT",
         "address": "1625 Leavenworth St", "neighborhood": "Nob Hill",
         "lat": 37.7959983, "lng": -122.4169553},
    ]
    uniq.sort(key=lambda v: v["name"])
    with open(OUT, "w") as f:
        json.dump({"venues": uniq}, f, indent=0)
    types = collections.Counter(v["permit_type"] for v in uniq)
    print(f"wrote {len(uniq)} venues -> {OUT}")
    print("top permit types:")
    for t, n in types.most_common(10):
        print(f"  {n:5d}  {t}")

if __name__ == "__main__":
    main()
