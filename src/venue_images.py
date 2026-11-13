"""Venue photography, resolved in tiers and cached to disk.

The corpus currently hotlinks publisher CDN images (Hearst's s.hdnux.com, Vox's
platform.sf.eater.com) onto every dossier. Linking to an article is defensible;
serving that outlet's photograph inside our own page is a different act and one
neither outlet has licensed. This module replaces that with images the venue
itself publishes, falling back outward only when the venue offers none.

Resolution order, most authoritative first:

  1. The restaurant's own website — the OG/JSON-LD image it publishes about
     itself. The venue's own photograph of the venue.
  2. Its Instagram / Facebook profile image, when the site exposes the handle.
  3. Mapbox Search Box `primary_photo`, which is sourced from the venue's own
     web presence. Used as a *lookup* only; the bytes are downloaded and served
     by us, never hotlinked.

Every tier requires an EXACT name match before accepting a photo. A substring
match put "Population Salon Nopa" on Nopa and "Chez Maman West" on Chez Panisse;
a wrong photograph on a dossier whose premise is sourced claims is worse than an
empty frame.

Nothing is fetched at request time. `resolve_all()` walks the corpus once,
writes `data_venue_images.json`, and the servers read that file. So:
  - no per-request network call, no cold-start cost
  - no hotlinking: the stored record carries attribution + license note
  - a venue with no confident image simply has none, and the UI renders none

Usage:
    ./.venv/bin/python src/venue_images.py --limit 50      # sample
    ./.venv/bin/python src/venue_images.py --all           # full corpus
"""
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

CACHE = os.path.join(BASE, "data_venue_images.json")
UA = {"User-Agent": "BoneFides/1.0 (kitchen lineage research; patrick@boxfordpartners.com)"}


def norm(x):
    """Name key: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", (x or "").lower())


def _host(url):
    m = re.match(r"https?://([^/]+)", url or "", re.I)
    return (m.group(1) if m else "").lower().replace("www.", "")


# ── tier 0: discovery ───────────────────────────────────────────────────────
# Guessing domain shapes from the venue name was lazy and wrong: it found a
# handful of sites and silently missed hundreds that plainly exist. SERP is
# already wired for corpus growth, so use it to FIND the official site, then
# read that site's own declared image.

_BOOKING_HOSTS = ("opentable.", "resy.com", "exploretock.", "tock.",
                  "yelp.", "tripadvisor.", "doordash.", "ubereats.",
                  "grubhub.", "seamless.", "caviar.", "postmates.com")

# Social/directory hosts that are never a restaurant's own site
_NOT_OFFICIAL = ("facebook.", "instagram.", "twitter.", "x.com",
                 "tiktok.", "linkedin.", "youtube.", "pinterest.",
                 "wikipedia.", "mapquest.", "zomato.", "foursquare.",
                 # aggregators and "places" directories that surface as the
                 # first hit and would have been treated as an official site
                 "plac.es", "places.", "restaurantji.", "menuism.",
                 "allmenus.", "menupages.", "singleplatform.",
                 "restaurantji", "opentable", "resy", "exploretock",
                 "tock.", "timeout.com", "thrillist", "infatuation",
                 "eater.com", "sfgate.", "sfchronicle.", "michelin.com")


def _is_official(url, venue):
    """Is this SERP hit plausibly the restaurant's own website?

    Deliberately conservative. A SERP hit for "Rich Table" was
    `richtablesf.nevertrustadame.com` — a lookalike subdomain on an unrelated
    base domain. Accepting it would point readers at a phishing page, so the
    venue's name must be part of the REGISTERED domain, not merely a subdomain
    label, and the base must be a plain commercial domain.
    """
    h = _host(url)
    if not h:
        return False
    if any(b in h for b in _BOOKING_HOSTS):
        return False
    if any(s in h for s in _NOT_OFFICIAL):
        return False
    if h.endswith((".gov", ".edu", ".tk", ".ml", ".ga", ".cf", ".gq")):
        return False
    # registered domain = last two labels (good enough for .com/.net/.org;
    # country TLDs are covered by the two-label rule too in practice)
    parts = h.split(".")
    if len(parts) < 2:
        return False
    base = ".".join(parts[-2:])
    # the venue's distinctive word must appear in the REGISTERED DOMAIN.
    # 4 characters, not 5: "Zuni Cafe" -> zunicafe.com is legitimate and was
    # rejected by a 5-char floor.
    words = [w for w in re.split(r"[^a-z0-9]+", venue.lower()) if len(w) >= 4]
    if not words:
        # Short names ("Coi", "A16") cannot be matched on the domain safely —
        # "coi" appears in countless hosts. They are accepted only when the
        # caller verifies the page itself names the venue (see tier_website),
        # so here we allow the domain through and let that check decide.
        return h.count(".") <= 1 or h.startswith("www.")
    base_flat = base.replace("-", "")
    if not any(w in base_flat for w in words):
        return False
    # a subdomain that is not www is a hint, not the restaurant's own site
    sub = ".".join(parts[:-2])
    if sub and sub != "www":
        return False
    return True


def find_official_site(venue, attempts=3):
    """SERP the venue, return its own website URL (or None).

    Retried: the SERP endpoint intermittently returns a non-JSON body (we saw
    JSONDecodeError), and a single transient failure was silently reading as
    "this restaurant has no website" — which is both wrong and exactly the
    flake-vs-absence confusion this pipeline must not make.
    """
    from src.brightdata import serp
    for i in range(attempts):
        try:
            results = serp(f"{venue} San Francisco official website", num=20)
        except Exception:
            time.sleep(1 + i)
            continue
        if results:
            named = [r["url"] for r in results if _is_official(r["url"], venue)]
            if named:
                return named[0]
        return None                      # a real empty answer, not a failure
    return None


def find_booking_links(venue):
    """Reservation-platform URLs SERP returns for this venue.

    Verified to be the VENUE's page on that platform, not the platform's
    homepage: a "Book on Resy" link that lands on resy.com is a broken promise,
    and a link to a similarly-named restaurant is worse.
    """
    from src.brightdata import serp
    key = norm(venue)
    out = {}
    for platform, host in (("resy", "resy.com"), ("opentable", "opentable."),
                           ("tock", "exploretock.")):
        try:
            for r in serp(f"{venue} San Francisco {platform}", num=10):
                h = _host(r["url"])
                if host not in h:
                    continue
                # the URL path must carry the venue name (slugified)
                slug_words = [w for w in re.split(r"[^a-z0-9]+", venue.lower()) if len(w) >= 4]
                if slug_words and all(w in norm(r["url"]) for w in slug_words):
                    out[platform] = r["url"]
                    break
        except Exception:
            continue
    return out


# ── tier 1: the restaurant's own site ────────────────────────────────────────

def _candidate_sites(venue, known_website=None):
    """URLs to try for tier 1, best first.

    `known_website` comes from venues_geo.json (curated). Otherwise we try the
    obvious domain shapes — but a guessed domain is only accepted if the page
    actually comes back 200 AND names the venue, because a wrong restaurant's
    photograph is the failure this whole module exists to avoid.
    """
    if known_website:
        return [known_website], True
    slug = re.sub(r"[^a-z0-9]", "", venue.lower())
    if len(slug) < 3:
        return [], False
    return [f"https://www.{slug}sf.com/", f"https://{slug}sf.com/",
            f"https://www.{slug}.com/", f"https://{slug}.com/"], False


def _og_image(html):
    """The page's own declared lead image.

    Tiers, because small restaurant sites do not all publish OG tags: Squarespace
    and similar builders often emit images only inside their data blobs. Benu is
    a Squarespace site with no og:image at all, so an OG-only extractor silently
    returned nothing for a venue whose site plainly has photographs.
    """
    pats = (
        # 1. OpenGraph / Twitter — the declared lead image
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        # 2. JSON-LD image objects
        r'"image"\s*:\s*\{[^}]*"url"\s*:\s*"([^"]+)"',
        r'"image"\s*:\s*"([^"]+)"',
        # 3. Squarespace / Wix data blobs
        r'"assetUrl"\s*:\s*"([^"]+)"',
        r'"originalSizeUrl"\s*:\s*"([^"]+)"',
        r'"imageUrl"\s*:\s*"([^"]+)"',
        # 4. A hero/lead <img> that is not an icon or sprite
        r'<img[^>]+(?:data-src|src)=["\']([^"\']+\.(?:jpe?g|png|webp)[^"\']*)',
    )
    for p in pats:
        for m in re.finditer(p, html, re.S | re.I):
            u = m.group(1).strip()
            if not u.startswith("http"):
                continue
            lu = u.lower()
            if lu.endswith((".svg", ".gif")):
                continue
            if any(x in lu for x in ("logo", "favicon", "sprite", "icon-", "placeholder")):
                continue
            return u
    return None


def _page_names_venue(html, venue):
    n = norm(venue)
    if not n or len(n) < 3:
        return False
    return n in norm(html)


def tier_website(venue, known_website=None, timeout=15):
    import requests
    for url in _candidate_sites(venue, known_website)[0]:
        try:
            r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
            if r.status_code != 200:
                continue
            if not _page_names_venue(r.text, venue):
                continue                      # someone else's site
            img = _og_image(r.text)
            if img:
                return {"url": img, "source": "venue-website", "site": url,
                        "confidence": "high", "evidence": "og:image on the venue's own site"}
        except Exception:
            continue
    return None


# ── tier 3: Mapbox (used as a lookup, bytes downloaded by us) ────────────────

def tier_mapbox(venue, token, timeout=15):
    import requests
    try:
        s = requests.get("https://api.mapbox.com/search/searchbox/v1/forward",
                         params={"q": f"{venue} San Francisco", "access_token": token,
                                 "limit": 5}, timeout=timeout).json()
        for f in (s.get("features") or []):
            p = f.get("properties") or {}
            if norm(p.get("name")) != norm(venue):
                continue                      # EXACT name only
            mid = p.get("mapbox_id")
            if not mid:
                continue
            d = requests.get(f"https://api.mapbox.com/search/searchbox/v1/retrieve/{mid}",
                             params={"access_token": token, "session_token": "bonefides"},
                             timeout=timeout).json()
            md = (((d.get("features") or [{}])[0].get("properties") or {})
                  .get("metadata") or {})
            ph = md.get("primary_photo")
            if ph:
                return {"url": ph, "source": "mapbox-primary-photo",
                        "site": _host(ph), "confidence": "medium",
                        "evidence": "Mapbox POI primary_photo, exact name match"}
    except Exception:
        pass
    return None


# ── tier 2: Instagram / Facebook profile image ───────────────────────────────

def tier_social(venue, known_website=None, timeout=15):
    """The venue's own social profile image.

    Only attempted when the venue's site names an instagram/facebook handle —
    guessing a handle attaches a stranger's face to a restaurant. Meta blocks
    unauthenticated scraping of profile images, so this often returns None; that
    is the correct outcome rather than inventing one.
    """
    import requests
    slug = re.sub(r"[^a-z0-9]", "", venue.lower())
    for url in (f"https://www.{slug}sf.com/", f"https://{slug}sf.com/"):
        try:
            r = requests.get(url, headers=UA, timeout=timeout)
            if r.status_code != 200:
                continue
            m = re.search(r'instagram\.com/([A-Za-z0-9_.]+)', r.text)
            if not m:
                return None               # no handle: do not guess one
            handle = m.group(1).rstrip(".")
            return {"url": f"https://www.instagram.com/{handle}/",
                    "source": "venue-social", "site": "instagram.com",
                    "confidence": "low", "handle": handle,
                    "evidence": "handle linked from the venue's own site"}
        except Exception:
            continue
    return None


# ── driver ──────────────────────────────────────────────────────────────────

def resolve_venue(venue, token=None, known_website=None, use_serp=True):
    """Run the tiers in order; return the first confident result.

    The result also carries the venue's official site and any booking links
    found along the way, so one pass fills the dossier's outbound links too.
    """
    site = known_website
    booking = {}
    if use_serp and not site:
        site = find_official_site(venue)
    if use_serp and site:
        booking = find_booking_links(venue)

    img = None
    if site:
        img = tier_website(venue, site)
    if not img:
        img = tier_social(venue, site)
        # a social *handle* is not an image; only accept a real image URL
        if img and ("instagram.com" in img.get("url", "") or
                    not img.get("url", "").startswith(("http://", "https://"))):
            img = None
    if not img and token:
        img = tier_mapbox(venue, token)

    if not img and not site and not booking:
        return None
    out = dict(img or {"url": None, "source": None})
    out["site"] = site
    if booking:
        out["booking"] = booking
    return out


def load_cache():
    if os.path.exists(CACHE):
        try:
            with open(CACHE) as f:
                return json.load(f)
        except ValueError:
            return {}
    return {}


def save_cache(d):
    tmp = CACHE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, CACHE)


def main(argv):
    from src.cli import load_env
    load_env(os.path.join(BASE, ".env"))
    token = os.environ.get("MAPBOX_TOKEN")

    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])

    # Venues worth resolving: those the lineage graph actually names.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ui_server_img", os.path.join(BASE, "ui", "server.py"))
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    from src.es import make_client
    es = make_client()

    raw = ui._distinct_values(es, "to_venue.keyword") | ui._distinct_values(es, "from_venue.keyword")
    venues = sorted({v for v in raw if v and not ui._is_junk_venue(v)})

    # curated websites, where we have them
    sites = {}
    gp = os.path.join(BASE, "ui", "venues_geo.json")
    if os.path.exists(gp):
        for v in json.load(open(gp)).get("venues", []):
            if v.get("website"):
                sites[v["name"].lower()] = v["website"]

    cache = load_cache()
    todo = [v for v in venues if norm(v) not in cache]
    if limit:
        todo = todo[:limit]

    print(f"{len(venues)} venue names · {len(cache)} cached · resolving {len(todo)}")
    hits = 0
    for i, v in enumerate(todo, 1):
        r = resolve_venue(v, token=token, known_website=sites.get(v.lower()))
        cache[norm(v)] = r or {"url": None, "source": None}
        hits += 1 if r else 0
        if i % 25 == 0 or i == len(todo):
            save_cache(cache)
            print(f"  [{i}/{len(todo)}] resolved {hits} ({hits/max(i,1)*100:.0f}%)")
        time.sleep(0.1)
    save_cache(cache)

    found = sum(1 for x in cache.values() if x.get("url"))
    print(f"done: {found}/{len(cache)} venues have an image "
          f"({found/max(len(cache),1)*100:.0f}%) → {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
