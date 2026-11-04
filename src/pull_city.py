"""Pull every permitted food business (SF DPH inspections dataset tvy3-wexg)
into ui/city_venues.json — the "universe" layer for the map.

One row per permit (dedup by permit_number), keep only rows with lat/lng.
Restaurants (H24 - RESTAURANT...) are the headline class; bars/bakeries/cafes
also included — everything permitted that serves food/drink.
"""
import json, os, collections, requests

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
