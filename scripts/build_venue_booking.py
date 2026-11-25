"""Write ui/venue_booking.json: verified Resy / OpenTable / Tock pages per map pin.

src/venue_images.py stores booking pages it found per corpus venue name in
crawl/venue_images.json. Corpus names and map pins (SF permit data plus the
curated geocode cache) do not line up one to one, and some stored links point
at a same-named restaurant in another city. The map must never offer a
"Book on ..." button for the wrong restaurant, so a link is kept only when:

  - the pin's name (or lineage name) has a cache record with that link,
  - the URL passes the same host and path checks find_booking_links applies,
  - its slug names the PIN's venue on a word boundary, and
  - every other slug word is neutral (platform path, "san-francisco", generic
    dining words). A leftover word such as a city or a second name means a
    different restaurant, so the link is dropped.

The output maps each pin's exact name to {platform: url} (pins with a verified
link only). build.sh ships it with the API, and src/dossier.venues_geo()
attaches it to /api/venues as `booking`. Re-run after src/venue_images.py
finds new booking pages.

Usage: .venv/bin/python scripts/build_venue_booking.py [--report]
"""
import json
import os
import re
import sys
import urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from src import dossier  # noqa: E402
from src.venue_images import (  # noqa: E402
    _DIRECTORY_PATH_SEGMENTS, _booking_city_mismatch, _host, _slug_names_venue, norm,
)

CACHE = os.path.join(BASE, "crawl", "venue_images.json")
OUT = os.path.join(BASE, "ui", "venue_booking.json")

HOSTS = {"resy": "resy.com", "opentable": "opentable.com", "tock": "exploretock.com"}

# Slug words that say nothing about WHICH restaurant: platform path parts,
# San Francisco itself, and generic dining words. Every other slug word must be
# one of the pin's own words. A leftover word is how a same-named restaurant
# elsewhere shows up (`la-victoria-tampa`, `gather-berkeley`), and also how a
# different SF place shows up (`buon-gusto-south-san-francisco` for "Gusto").
_NEUTRAL = {"r", "cities", "venues", "san", "francisco", "sf", "ca", "san-francisco-ca",
            "restaurant", "restaurants", "and", "the", "of", "at", "by", "a", "an",
            "bar", "cafe", "kitchen", "dining", "room", "reservations", "www"}
# Permit-register noise in pin names: "Angler Sf, Llc", "Ernest Restaurant /
# Befr Llc". Cut at "/" or ",", then drop these words.
_LEGAL = {"llc", "inc", "corp", "co", "ltd", "lp", "sf", "cal", "dba", "restaurant"}


def clean_name(name):
    head = re.split(r"[/,]", name or "")[0]
    # A possessive joins, as in slugs ("Akiko's" -> akikos); counting its "s"
    # as a word let "Schroeder's" pass the multi-word rule. Any other
    # apostrophe separates ("Fior D'Italia" -> fior d italia), and
    # _leftover_words still accepts the joined slug form (/lardoise).
    head = re.sub(r"['\u2019]s\b", "s", head, flags=re.I)
    head = re.sub(r"['\u2019]", " ", head)
    words = [w for w in re.split(r"[^a-z0-9]+", head.lower()) if w and w not in _LEGAL]
    if len(words) > 1 and words[0] == "the":  # the slug matcher does not skip a leading "the"
        words = words[1:]
    return " ".join(words)


def _path_ok(platform, url):
    host = _host(url).rstrip(".")
    want = HOSTS[platform]
    if host not in (want, "www." + want):
        return False
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(parts.path).lower()
    bad = ("/city/", "/search", "/discover", "/cuisine/", "/neighborhood/", "/blog/",
           "/stories/", "/article/", "/news/", "/guides/", "/list/") + _DIRECTORY_PATH_SEGMENTS
    if any(seg in path for seg in bad):
        return False
    if "/cities/" in path and "/venues/" not in path:
        return False
    if path.rstrip("/") in ("/s", "/searches", "") or "query=" in (parts.query or "").lower():
        return False
    return not _booking_city_mismatch(path, parts.query)


def _leftover_words(path, name):
    """Slug words that are neither the pin's own words nor neutral.

    A slug may run the name together (`/garydanko`, `/zunicafe`), which
    _slug_names_venue accepts. Joins of consecutive own words therefore count
    as own words too; anything else left over still means another place."""
    words = set(re.split(r"[^a-z0-9]+", path.lower())) - {""}
    own = _own_forms(name)
    own |= {o + sf for o in own for sf in _SF_SUFFIXES}  # /trestlesf
    return sorted(w for w in words - own - _NEUTRAL if not w.isdigit())


_SF_SUFFIXES = ("sf", "sanfrancisco")


def _own_forms(name):
    """The pin's words plus every run-together join of consecutive words."""
    parts = name.split()
    return set(parts) | {"".join(parts[i:j]) for i in range(len(parts))
                         for j in range(i + 2, len(parts) + 1)}


def _names_sf(path, name):
    """Does the path name San Francisco, as its own slug word or joined to
    the venue's name (`/trestlesf`)?"""
    if _SF.search(path.lower()):
        return True
    words = set(re.split(r"[^a-z0-9]+", path.lower()))
    return any(o + sf in words for o in _own_forms(name) for sf in _SF_SUFFIXES)


_SF = re.compile(r"san-francisco|sanfrancisco|(^|[^a-z])sf([^a-z]|$)")
_STOP = {"the", "and", "of", "a", "an", "at", "by"}


def verified(platform, url, pin_names):
    """The first cleaned pin name this booking URL provably belongs to, or None.

    pin_names[0] is the pin's own (permit or curated) name. A URL with no city
    (`opentable.com/kaya`, `/r/hearth`) is a guess unless that name has two or
    more words and matches it: "Kaya", "Sasa" and "Hearth" are restaurants in
    other towns too. Later entries, if a caller passes them, may only vouch
    for a URL that names San Francisco."""
    if platform not in HOSTS or not isinstance(url, str) or not _path_ok(platform, url):
        return None
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    for i, name in enumerate(pin_names):
        if not name or not _slug_names_venue(path, name) or _leftover_words(path, name):
            continue
        in_sf = _names_sf(path, name)
        # single letters ("l" in L'Ardoise) do not make a name distinctive
        if in_sf or (i == 0 and len({w for w in name.split() if len(w) > 1} - _STOP) >= 2):
            return name
    return None


def _cache_keys(pin):
    """Cache keys to try for a pin. The crawl keyed some venues by their short
    name ("zuni" for Zuni Cafe), so also try each name without trailing
    generic words. Verification below still requires the URL to name the pin."""
    keys = []
    for n in (pin.get("lineage_name"), pin.get("name")):
        if not n:
            continue
        keys.append(norm(n))
        words = clean_name(n).split()
        while len(words) > 1 and words[-1] in _NEUTRAL:
            words.pop()
            keys.append(norm(" ".join(words)))
    return list(dict.fromkeys(k for k in keys if k))


def build():
    cache = json.load(open(CACHE))
    out, rejected = {}, []
    for pin in dossier.venues_geo():
        for name in _cache_keys(pin):
            rec = cache.get(name) or {}
            # Only the pin's OWN name can vouch for a link. The lineage name
            # is a looser corpus link ("Balboa Produce" -> "Balboa"), and let
            # a produce market inherit Balboa Cafe's OpenTable page.
            pin_names = [clean_name(pin.get("name"))]
            links = {}
            for platform, url in sorted((rec.get("booking") or {}).items()):
                if verified(platform, url, pin_names):
                    links[platform] = url
                else:
                    rejected.append((pin["name"], url))
            if links:
                out[pin["name"]] = links
                break
    return out, rejected


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    out, rejected = build()
    with open(OUT + ".tmp", "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(OUT + ".tmp", OUT)
    print(f"wrote {OUT}: {len(out)} pins with a verified booking page, {len(rejected)} links rejected")
    if "--report" in argv:
        for name, url in rejected:
            print(f"  reject {name!r}: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
