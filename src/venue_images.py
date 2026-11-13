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
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

CACHE = os.path.join(BASE, "data_venue_images.json")
# Downloaded venue photos live under ui/ so both server twins can serve them
# statically without a third-party request at render time.
IMG_DIR = os.path.join(BASE, "ui", "venue-images")
UA = {"User-Agent": "BoneFides/1.0 (kitchen lineage research; patrick@boxfordpartners.com)"}


def norm(x):
    """Name key: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", (x or "").lower())


def _host(url):
    m = re.match(r"https?://([^/]+)", url or "", re.I)
    h = (m.group(1) if m else "").lower()
    h = h.split(":")[0]                       # strip port
    # strip a LEADING www. only — .replace() everywhere turned "newww.com"
    # into "necom" and could make an unrelated host look like a venue's own
    return h[4:] if h.startswith("www.") else h


# ── SSRF guard ──────────────────────────────────────────────────────────────
# Search results reach requests.get() and redirects are followed. An operator
# who controls an accepted domain can redirect to a private service, so every
# destination — the initial URL AND each hop — is resolved and checked before
# the request is made.

_PRIVATE_NETS = [
    ipaddress.ip_network(n) for n in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
        "169.254.0.0/16", "0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24",
        "192.0.2.0/24", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
        "224.0.0.0/4", "240.0.0.0/4",
        "::1/128", "fc00::/7", "fe80::/10", "::/128", "2001:db8::/32",
    )
]


def _is_public_host(host):
    """True only if every address the host resolves to is public."""
    if not host:
        return False
    h = host.split(":")[0].strip("[]")
    if h in ("localhost", "localhost.localdomain"):
        return False
    try:
        infos = socket.getaddrinfo(h, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local \
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
        if any(ip in net for net in _PRIVATE_NETS):
            return False
    return True


def _url_is_public(url):
    m = re.match(r"https?://([^/]+)", url or "", re.I)
    if not m:
        return False
    if not (url or "").lower().startswith(("http://", "https://")):
        return False
    return _is_public_host(m.group(1))


def safe_get(url, timeout=20, max_redirects=5):
    """GET that refuses to touch a private address, on the first hop or any
    redirect. Returns the response, or None when the destination is unsafe or
    the chain is too long.

    Redirects are followed manually so each destination is checked; letting
    requests follow them silently is what made this SSRF-able.
    """
    import requests
    current = url
    for _ in range(max_redirects + 1):
        if not _url_is_public(current):
            return None
        try:
            r = requests.get(current, headers=UA, timeout=timeout,
                             allow_redirects=False)
        except Exception:
            return None
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            nxt = urllib.parse.urljoin(current, r.headers["location"])
            if not _url_is_public(nxt):
                return None
            current = nxt
            continue
        return r
    return None


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
        # "coi" appears in countless hosts. They are never accepted on the
        # domain alone; only tier_website's page-names-venue check can admit
        # one, and it must run before the site is saved.
        return False
    base_flat = base.replace("-", "")
    if not any(w in base_flat for w in words):
        return False
    # a subdomain that is not www is a hint, not the restaurant's own site
    sub = ".".join(parts[:-2])
    if sub and sub != "www":
        return False
    return True


def find_official_site(venue, attempts=3):
    """SERP the venue, return its own website URL.

    Returns a TUPLE (url, status) where status is one of:
      "found"    — a candidate whose page verified as the venue's
      "absent"   — SERP answered clearly and no candidate qualified
      "failed"   — SERP errored out; the answer is unknown, not negative

    The distinction is load-bearing. Caching "failed" as "no website" made an
    outage permanent: every later run skipped the venue because the cache said
    it had nothing, even after the service recovered.
    """
    from src.brightdata import serp
    errored = False
    for i in range(attempts):
        try:
            results = serp(f"{venue} San Francisco official website", num=20)
        except Exception:
            errored = True
            time.sleep(1 + i)
            continue
        candidates = [r["url"] for r in (results or []) if _is_official(r["url"], venue)]
        # Try each candidate until one VERIFIES. Returning the first allowed
        # domain saved unverified sites (the cache held theindependentsf.com
        # for venue "24", which _page_names_venue rejects outright).
        for url in candidates:
            r = safe_get(url)
            if r is None or r.status_code != 200:
                continue
            if not _page_names_venue(r.text, venue):
                continue
            return (r.url or url), "found"
        return None, "absent"            # SERP answered, nothing qualified
    return None, ("failed" if errored else "absent")


def find_booking_links(venue):
    """Reservation-platform URLs SERP returns for this venue.

    Verified to be the VENUE's page on that platform, not the platform's
    homepage: a "Book on Resy" link that lands on resy.com is a broken promise,
    and a link to a similarly-named restaurant is worse.
    """
    from src.brightdata import serp
    out = {}
    for platform, host in (("resy", "resy.com"), ("opentable", "opentable."),
                           ("tock", "exploretock.")):
        try:
            for r in serp(f"{venue} San Francisco {platform}", num=10):
                h = _host(r["url"])
                if host not in h:
                    continue
                # blog./help./support. subdomains are editorial or support, not
                # booking. A "Book on Resy" link pointed at blog.resy.com.
                sub = h.split(".")[0]
                if h.count(".") > 1 and sub not in ("www", host.rstrip(".")):
                    continue
                if sub in ("blog", "help", "support", "news", "press", "about"):
                    continue
                parts = urllib.parse.urlsplit(r["url"])
                path = urllib.parse.unquote(parts.path).lower()
                # A SEARCH page is not a booking page: resy.com/city/san-francisco
                # ?query=Rich%20Table passed the old whole-URL check and would
                # have been offered as "Book on Resy".
                if any(seg in path for seg in ("/city/", "/search", "/discover",
                                               "/cuisine/", "/neighborhood/",
                                               "/blog/", "/stories/", "/article/",
                                               "/news/", "/guides/")):
                    continue
                # OpenTable's search is a bare "/s"
                if path.rstrip("/") in ("/s", "/searches", ""):
                    continue
                if parts.query and "query=" in parts.query.lower():
                    continue
                # the venue must appear in the PATH, not the query string
                full = norm(venue)
                if full and full in norm(path):
                    out[platform] = r["url"]
                    break
                # short names (Coi, A16) have no 4+ char token, so the token
                # check is skipped for them and the full-name path match above
                # is the only evidence — which is why it is exact.
                words = [w for w in re.split(r"[^a-z0-9]+", venue.lower()) if len(w) >= 4]
                if words and all(w in norm(path) for w in words):
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


def _og_image(html, base_url=""):
    """The page's own declared lead image, absolutized against the page.

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
            if not u:
                continue
            # Relative and protocol-relative paths are real image declarations.
            # Dropping them lost the hero on sites that write /images/hero.jpg.
            u = urllib.parse.urljoin(base_url or "", u)
            if not u.lower().startswith(("http://", "https://")):
                continue
            fname = urllib.parse.urlsplit(u).path.rsplit("/", 1)[-1].lower()
            # decode so "social%2Bicon.png" and "social+icon.png" both read as
            # filenames — the committed 20spot record captured one of these as
            # a high-confidence hero photo
            fname = urllib.parse.unquote(fname).replace("+", " ")
            if fname.endswith((".svg", ".gif", ".ico")):
                continue
            if any(x in fname for x in ("logo", "favicon", "sprite", "icon",
                                        "placeholder", "default", "spacer",
                                        "avatar", "badge")):
                continue
            return u
    return None


def _page_names_venue(html, venue):
    """Does the page name this venue anywhere in its visible text?

    Searches the TEXT, not the raw markup: normalizing the whole HTML made tag
    names, class names and script payloads count as a match, so a page could
    "name" a venue it never mentions.
    """
    n = norm(venue)
    if not n:
        return False
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return n in norm(text)


def tier_website(venue, known_website=None, timeout=15):
    """The venue's own page, fetched only from a public address, redirects
    checked hop by hop. Returns None unless the page both names the venue and
    declares an image."""
    for url in _candidate_sites(venue, known_website)[0]:
        r = safe_get(url, timeout=timeout)
        if r is None or r.status_code != 200:
            continue
        if not _page_names_venue(r.text, venue):
            continue                          # someone else's site
        img = _og_image(r.text, base_url=r.url or url)
        if img:
            return {"url": img, "source": "venue-website", "site": r.url or url,
                    "confidence": "high",
                    "evidence": "declared image on the venue's own site"}
    return None


def download_image(url, venue_key, timeout=25):
    """Fetch an image once and store it locally. Returns a relative path or None.

    This is the half that makes "lookup only" true: a remote URL in the cache
    would still be a hotlink, which is the exact thing this module exists to
    remove. Nothing is served from a third-party CDN at render time.
    """
    if not url or not _url_is_public(url):
        return None
    r = safe_get(url, timeout=timeout)
    if r is None or r.status_code != 200:
        return None
    ctype = (r.headers.get("content-type") or "").lower()
    if not ctype.startswith("image/"):
        return None
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
           "image/gif": ".gif"}.get(ctype.split(";")[0].strip(), ".jpg")
    os.makedirs(IMG_DIR, exist_ok=True)
    name = re.sub(r"[^a-z0-9]+", "-", venue_key.lower()).strip("-")[:80] or "venue"
    path = os.path.join(IMG_DIR, name + ext)
    with open(path, "wb") as f:
        f.write(r.content)
    return os.path.join("venue-images", name + ext)


# ── tier 3: Mapbox (used as a lookup, bytes downloaded by us) ────────────────

def tier_mapbox(venue, token, timeout=15):
    """Mapbox POI photo, DOWNLOADED — never stored as a remote URL."""
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
                local = download_image(ph, venue)
                if not local:
                    return None           # could not own the bytes: not resolved
                return {"url": local, "remote": ph, "source": "mapbox-primary-photo",
                        "site": _host(ph), "confidence": "medium",
                        "evidence": "Mapbox POI primary_photo, exact name match, "
                                    "downloaded locally"}
    except Exception:
        pass
    return None


# ── tier 2: Instagram / Facebook profile image ───────────────────────────────

def tier_social(venue, known_website=None, timeout=15):
    """The venue's own social profile image.

    Reads the CONFIRMED website (never a guessed domain — that produced requests
    that could not succeed) and returns an actual image URL.

    Meta serves profile pictures from a CDN, not the profile page, so this pulls
    the og:image the profile advertises. When Meta blocks the unauthenticated
    request the tier returns None, which is the correct outcome: a guessed
    handle would attach a stranger's face to a restaurant.
    """
    if not known_website:
        return None                       # nothing confirmed to read a handle from
    r = safe_get(known_website, timeout=timeout)
    if r is None or r.status_code != 200:
        return None
    m = re.search(r'(?:instagram|facebook)\.com/([A-Za-z0-9_.]+)', r.text)
    if not m:
        return None                       # no handle: do not guess one
    handle = m.group(1).rstrip(".")
    if handle in ("p", "reel", "explore", "accounts", "share", "login"):
        return None                       # a link path, not a profile
    profile = f"https://www.instagram.com/{handle}/"
    pr = safe_get(profile, timeout=timeout)
    if pr is None or pr.status_code != 200:
        return None
    img = _og_image(pr.text, base_url=pr.url or profile)
    if not img:
        return None
    return {"url": img, "source": "venue-social", "site": "instagram.com",
            "confidence": "low", "handle": handle,
            "evidence": "profile image from a handle linked by the venue's own site"}


# ── driver ──────────────────────────────────────────────────────────────────

def resolve_venue(venue, token=None, known_website=None, use_serp=True):
    """Run the tiers in order. Returns (record, status).

    status is "found", "absent" or "failed". Only "absent" may be cached as a
    negative result; "failed" must stay eligible so an outage does not become a
    permanent hole in the cache.
    """
    site = known_website
    status = "absent"
    booking = {}
    if use_serp and not site:
        site, status = find_official_site(venue)
        if status == "failed":
            return None, "failed"
    if use_serp and site:
        booking = find_booking_links(venue)

    img = None
    if site:
        img = tier_website(venue, site)
    if not img:
        img = tier_social(venue, site)      # reads only the CONFIRMED site
    if not img and token:
        img = tier_mapbox(venue, token)

    if not img and not site and not booking:
        return None, "absent"

    out = dict(img or {"url": None, "source": None})
    # Every tier must end with bytes we own. A remote URL left in the cache is
    # still a hotlink, which is the exact thing this module removes — so tier 1
    # and tier 2 download here too, not just Mapbox.
    if out.get("url") and str(out["url"]).startswith(("http://", "https://")):
        local = download_image(out["url"], venue)
        if local:
            out["remote"] = out["url"]
            out["url"] = local
        else:
            out["url"] = None            # could not own the bytes: not resolved
            out["source"] = None
    out["site"] = site
    if booking:
        out["booking"] = booking
    return out, "found"


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
    # A "failed" entry is retried on the next run; only a real answer is final.
    todo = [v for v in venues
            if norm(v) not in cache or cache[norm(v)].get("status") == "failed"]
    if limit:
        todo = todo[:limit]

    print(f"{len(venues)} venue names · {len(cache)} cached · resolving {len(todo)}")
    hits = 0
    for i, v in enumerate(todo, 1):
        r, status = resolve_venue(v, token=token, known_website=sites.get(v.lower()))
        if status == "failed":
            # do NOT cache: an outage must not look like "this venue has no site"
            cache[norm(v)] = {"url": None, "source": None, "status": "failed"}
        else:
            cache[norm(v)] = dict(r or {"url": None, "source": None}, status=status)
            hits += 1 if (r and r.get("url")) else 0
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
