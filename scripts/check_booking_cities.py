"""Read the city off booking pages whose URL names none, via Tavily extract.

scripts/build_venue_booking.py accepts a URL such as opentable.com/black-cat
only when the page itself says San Francisco: name matching alone put a
Longmont, Colorado "Black Cat" on an SF pin. This script finds every such URL
that passes the other checks, extracts the page (Tavily: 1 credit per 5
URLs; a page the basic depth cannot read is retried at the advanced depth),
and records its city in crawl/booking_cities.json. URLs already in the
file are skipped. A page that cannot be read is recorded as null; the build
then falls back to requiring two or more real words in the pin's own name.
Delete the entry to retry. Results are saved after every batch, so a failed
run resumes without paying for finished pages again.

Usage: .venv/bin/python scripts/check_booking_cities.py
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "scripts"))

from src import tavily  # noqa: E402
import build_venue_booking as bvb  # noqa: E402

EXTRACT = "https://api.tavily.com/extract"
_SOUTH_SF = re.compile(r"\bSouth San Francisco$")
_ADDRESS = re.compile(r"([A-Z][A-Za-z .'-]{2,30}),\s*([A-Z]{2})\s+\d{5}")


def city_of(text):
    """The restaurant's city as the page states it, or None.

    An address outside San Francisco wins ('Longmont, CO'). Otherwise an SF
    address, or a plain mention of San Francisco, means San Francisco.
    Reviewer locations ("San Francisco12 reviews") are not the restaurant's
    city and are ignored."""
    text = re.sub(r"San Francisco\s*\d+\s*reviews?", "", text or "")
    for m in _ADDRESS.finditer(text):
        city, state = m.group(1).strip(), m.group(2)
        # the capture may carry street words ("Ave San Francisco"); South San
        # Francisco is a separate city and must stay one
        is_sf = state == "CA" and city.endswith("San Francisco") and not _SOUTH_SF.search(city)
        if not is_sf:
            return f"{city}, {state}"
    if re.search(r"(?<!South )San Francisco", text):
        return "San Francisco"
    return None


def pending(cities):
    """City-less URLs that pass every other check and have no city on file.

    Selected by whether the URL path names San Francisco, not by whether the
    strict build already accepts it: the two-word name fallback would accept
    an unchecked /black-cat and it would never be read."""
    loose, _ = bvb.build(require_city=False)
    urls = set()
    for name, links in loose.items():
        for url in links.values():
            path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
            if url not in cities and not bvb._names_sf(path, bvb.clean_name(name)):
                urls.add(url)
    return sorted(urls)


def extract(key, urls, depth="basic"):
    body = {"urls": urls, "extract_depth": depth}
    req = urllib.request.Request(EXTRACT, data=json.dumps(body).encode(), headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    got = {x["url"]: city_of(x.get("raw_content")) for x in d.get("results", [])}
    return {u: got.get(u) for u in urls}


def save(cities):
    with open(bvb.CITIES + ".tmp", "w") as f:
        json.dump(cities, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(bvb.CITIES + ".tmp", bvb.CITIES)


def main():
    key = tavily._load_key()
    if not key:
        print("TAVILY_API_KEY is not set in .env", file=sys.stderr)
        return 1
    cities = bvb.load_cities()
    todo = pending(cities)
    print(f"{len(todo)} city-less booking URLs to check")
    for i in range(0, len(todo), 5):
        batch = todo[i:i + 5]
        found = extract(key, batch)
        retry = [u for u in batch if not found.get(u)]
        if retry:  # script-rendered pages (Tock) often need the advanced depth
            found.update({u: c for u, c in extract(key, retry, "advanced").items() if c})
        for url in batch:
            cities[url] = found.get(url)
            print(f"  {cities[url] or 'unknown':<22} {url}")
        save(cities)
    save(cities)
    return 0


if __name__ == "__main__":
    sys.exit(main())
