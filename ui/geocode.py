"""Geocode venue names via OpenStreetMap Nominatim; writes ui/venues_geo.json with website tags."""
import json, os, sys, time
import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src.cli import load_env
load_env(os.path.join(BASE, ".env"))

from src.es import make_client, INDEX

# Bay Area bounding box: out-of-town alumni destinations stay off the map
VIEWBOX = "-123.0,38.35,-121.5,37.15"

def venue_names(es):
    body = {"size": 0, "aggs": {
        "to": {"terms": {"field": "to_venue.keyword", "size": 300}},
        "fr": {"terms": {"field": "from_venue.keyword", "size": 300}},
    }}
    r = es.search(index=INDEX, body=body)
    names = set()
    for b in r["aggregations"]["to"]["buckets"] + r["aggregations"]["fr"]["buckets"]:
        if b["key"]:
            names.add(b["key"])
    # drop extraction noise: generic descriptors that would geocode to garbage
    drop = ("a ", "an ", "the ", "(pop-up)")
    return sorted(n for n in names if not n.lower().startswith(drop) and "(pop-up)" not in n)

def geocode(name):
    r = requests.get("https://nominatim.openstreetmap.org/search",
        params={"q": name + " San Francisco", "format": "jsonv2", "limit": 1, "extratags": 1,
                "countrycodes": "us", "viewbox": VIEWBOX, "bounded": 1},
        headers={"User-Agent": "bone-fides-demo/1.0 (hackathon; contact: demo)"}, timeout=15)
    r.raise_for_status()
    f = r.json()
    if not f:
        return None
    f = f[0]
    site = (f.get("extratags") or {}).get("website")
    if site and site.startswith("http://"):
        site = "https://" + site[len("http://"):]
    return {"lat": float(f["lat"]), "lng": float(f["lon"]), "website": site}

def main():
    es = make_client()
    out = []
    for name in venue_names(es):
        try:
            g = geocode(name)
        except Exception as e:
            print("skip", name, "->", e)
            continue
        if g:
            out.append({"name": name, **g})
        time.sleep(1.1)  # Nominatim usage policy
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venues_geo.json")
    with open(path, "w") as f:
        json.dump({"venues": out}, f, indent=1)
    print("geocoded %d venues -> %s" % (len(out), path))

if __name__ == "__main__":
    main()
