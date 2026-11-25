"""Look up Resy / OpenTable / Tock pages for map pins that have none, via Tavily.

One Tavily search per pin, limited to the three booking domains (1 credit
each on the basic depth), instead of src/venue_images.find_booking_links'
three general searches. Every result must pass the same verification as
scripts/build_venue_booking.py before it is saved, so a same-named restaurant
elsewhere is never stored for the pin. City-less URLs are saved here and
confirmed by scripts/check_booking_cities.py before the map uses them.

Accepted pages are merged into crawl/venue_images.json under the pin's cache
key (`booking`), and each looked-up pin is stamped `booking_checked` so a
re-run skips it. Then run scripts/check_booking_cities.py and
scripts/build_venue_booking.py.

Only restaurant pins the map can open (lineaged or Michelin, with a
restaurant permit or curated) are looked up.

Usage: .venv/bin/python scripts/find_booking_tavily.py [--limit N] [--dry-run]
"""
import argparse
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

VERBOSE = False

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "scripts"))

from src import dossier, tavily  # noqa: E402
from src.venue_images import norm  # noqa: E402
import build_venue_booking as bvb  # noqa: E402

CACHE = bvb.CACHE
RESTAURANT_PERMITS = ("H24", "H25", "H26")


def candidates(cache):
    out = []
    for pin in dossier.venues_geo():
        if not (pin.get("lineaged") or pin.get("michelin")) or pin.get("booking"):
            continue
        permit = pin.get("permit_type") or ""
        if permit and not permit.startswith(RESTAURANT_PERMITS):
            continue
        if (cache.get(norm(pin["name"])) or {}).get("booking_checked"):
            continue
        out.append(pin)
    return out


def lookup(key, name):
    body = json.dumps({
        "query": f"{name} San Francisco reservations",
        "max_results": 10,
        "search_depth": "basic",
        "include_domains": list(bvb.HOSTS.values()),
    }).encode()
    req = urllib.request.Request(tavily.ENDPOINT, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return [x["url"] for x in json.load(r).get("results", [])]


def accept(urls, pin):
    """Best verified page per platform. A URL that names San Francisco beats
    a city-less one whatever Tavily's order: the city-less page may belong to
    another town and be rejected by the city check later, and booking_checked
    stops a second search, so the SF page must not be thrown away."""
    name = bvb.clean_name(pin["name"])
    found, in_sf = {}, set()
    for url in urls:
        # drop tracking and language parameters (?lang=es, ?ref=...)
        url = url.split("?", 1)[0].split("#", 1)[0]
        for platform, host in bvb.HOSTS.items():
            if platform in in_sf or host not in url:
                continue
            if not bvb.verified(platform, url, [name], require_city=False):
                continue
            path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
            if bvb._names_sf(path, name):
                found[platform] = url
                in_sf.add(platform)
            else:
                found.setdefault(platform, url)
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="print every result Tavily returned")
    args = ap.parse_args(argv)
    global VERBOSE
    VERBOSE = args.verbose
    key = tavily._load_key()
    if not key:
        print("TAVILY_API_KEY is not set in .env", file=sys.stderr)
        return 1
    cache = json.load(open(CACHE))
    todo = candidates(cache)
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} pins to look up ({tavily.usage()})")
    hits = 0
    today = datetime.date.today().isoformat()
    for n, pin in enumerate(todo, 1):
        try:
            urls = lookup(key, bvb.clean_name(pin["name"]) or pin["name"])
        except Exception as e:
            print(f"  {pin['name']}: {type(e).__name__} {str(e)[:80]}")
            continue
        found = accept(urls, pin)
        if VERBOSE:
            print(f"  {pin['name']}: candidates {urls}")
        if found:
            hits += 1
            print(f"  {pin['name']}: {found}")
        rec = cache.setdefault(norm(pin["name"]), {"source": None, "url": None})
        rec["booking"] = {**(rec.get("booking") or {}), **found}
        if not rec["booking"]:
            del rec["booking"]
        rec["booking_checked"] = today
        if n % 25 == 0:
            print(f"  {n}/{len(todo)} looked up, {hits} with a page")
    print(f"{hits} of {len(todo)} pins gained a verified booking page")
    if not args.dry_run:
        with open(CACHE + ".tmp", "w") as f:
            json.dump(cache, f, indent=1, sort_keys=True)
        os.replace(CACHE + ".tmp", CACHE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
