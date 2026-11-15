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
import html as html_module
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


def safe_get(url, timeout=20, max_redirects=5, allow_broken_chain_for=None):
    """GET that refuses to touch a private address, on the first hop or any
    redirect. Returns the response, or None when the destination is unsafe or
    the chain is too long.

    Redirects are followed manually so each destination is checked; letting
    requests follow them silently is what made this SSRF-able.

    `allow_broken_chain_for` names ONE host whose incomplete TLS chain we
    accept (Commis serves a DigiCert GeoTrust leaf with no intermediate, so a
    client with a full trust store fails with "unable to verify the first
    certificate"; browsers fetch the missing intermediate, requests does not).
    It is a host, not a boolean, on purpose: verification is relaxed only when
    the host being fetched is that exact host. A redirect to anywhere else —
    or an image served from a different CDN — keeps full certificate checks,
    so a network attacker cannot trade on the exception to supply a false photo.
    """
    import requests
    current = url
    for _ in range(max_redirects + 1):
        if not _url_is_public(current):
            return None
        relax = bool(allow_broken_chain_for) and \
            _host(current) == allow_broken_chain_for.lower()
        try:
            r = requests.get(current, headers=UA, timeout=timeout,
                             allow_redirects=False)
        except Exception as e:
            if not relax or "CERTIFICATE_VERIFY_FAILED" not in str(e):
                return None
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                r = requests.get(current, headers=UA, timeout=timeout,
                                 allow_redirects=False, verify=False)
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
        # "coi" appears in countless hosts — so they are never accepted on the
        # domain ALONE. Returning False here rejected every SERP hit for them,
        # which meant their real site (coirestaurant.com) was never even tried
        # and got cached as absent forever. Let a short-name candidate through
        # only if the name is the WHOLE registered domain or its leading label
        # ("coirestaurant.com", "a16pizza.com"), and rely on the page-names-the-
        # venue check downstream to admit or reject it.
        short = [w for w in re.split(r"[^a-z0-9]+", venue.lower()) if w]
        if not short:
            return False
        squash = "".join(short)
        # A short name must be a WHOLE WORD in the label, not a prefix. Tested
        # against the label split on the places a brand would put a boundary:
        # start of the label, and before a descriptor word. `coirestaurant` and
        # `coisyntax` split as coi|restaurant / coi|syntax; `coinoprestaurant`
        # does not split after "coi" at all, so it is rejected. A startswith
        # test cannot tell those apart — coi is a prefix of all three.
        label = parts[-2].replace("-", "")
        bounds = ("restaurant", "restaurants", "cafe", "sf", "sanfrancisco",
                  "kitchen", "bar", "bistro", "grill", "pizza", "sushi",
                  "group", "hospitality", "dining", "food", "eatery")
        is_word = (label == squash) or any(
            label == squash + b or label == b + squash for b in bounds)
        if not is_word:
            return False
        sub = ".".join(parts[:-2])
        return not sub or sub == "www"
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
            if not _page_names_venue(r.text, venue, url=r.url or url):
                continue
            return (r.url or url), "found"
        return None, "absent"            # SERP answered, nothing qualified
    return None, ("failed" if errored else "absent")


def _slug_names_venue(path, venue):
    """Does this booking path name `venue`, on a boundary?

    Two shapes have to work at once:
      "Per Se"     -> /r/per-se          (name split across slug fragments)
      "Rich Table" -> /r/rich-table-...  (same)
      "Zuni Cafe"  -> /zunicafe          (name run together, no separators)
    and one has to fail:
      "Coi"        -> /r/coin-op-san-francisco

    A plain substring test passes the last one, because `coi` occurs inside
    `coinop`. Matching only whole fragments fixes that but then drops every
    venue whose words are too short (`per`/`se`) or whose slug is concatenated.
    So: the venue's words must appear as a CONSECUTIVE run of fragments, or as
    a run-together block inside one fragment — and in either case the match must
    consume whole fragments except at a word boundary, which `coin-op` fails.
    """
    bits = [b for b in re.split(r"[^a-z0-9]+", path.lower()) if b]
    if not bits:
        return False
    stop = {"and", "the", "of", "at", "by", "a", "an", "de", "la", "le"}
    raw = [w for w in re.split(r"[^a-z0-9]+", venue.lower()) if w]
    if not raw:
        return False

    # 1. EXACT full-name match first, over the whole path with separators
    #    removed. This is what accepts a slug joining every word of the name —
    #    /theprogress for "The Progress", /houseofprimerib for "House of Prime
    #    Rib" — where dropping connectives from the venue side alone leaves a
    #    name that can never match the joined path.
    #
    #    The match must consume the WHOLE fragment. A bare startswith would
    #    accept /theprogressbar for "The Progress", which is the same
    #    substring mistake as matching Coi inside Coin-Op.
    path_flat = "".join(bits)
    # "&" is written as "and" in a slug far more often than it is dropped:
    # "Sons & Daughters" -> /sonsanddaughterssf. Build both forms and accept
    # either, so the connective convention does not silently lose a venue.
    name_forms = {"".join(raw)}
    if "&" in venue:
        name_forms.add("".join(w if w != "&" else "and"
                               for w in re.split(r"(\s*&\s*)", venue.lower()) if w.strip()))
        name_forms.add("".join(re.split(r"[^a-z0-9]+",
                                        venue.lower().replace("&", "and"))))
    for nf in filter(None, name_forms):
        if path_flat == nf or any(b == nf for b in bits):
            return True
        if path_flat.startswith(nf) and path_flat[len(nf):] in _SLUG_TAILS:
            return True

    # 2. connectives dropped from BOTH sides, so "Sons & Daughters" matches
    #    /sons-and-daughters. A possessive trailing "s" is stripped so
    #    "Mister Jiu's" does not leave a stray word.
    words = [w for w in raw if w not in stop]
    if words and words[-1] == "s" and len(words) > 1:
        words = words[:-1]
    if not words:
        return False
    sig = [w for w in bits if w not in stop]
    if not sig:
        return False
    # A name reduced to ONE word identifies little on its own: "The Bird"
    # collapses to "bird", which appears inside /state-bird-provisions — a
    # different restaurant. One word has to earn it:
    #   - short (Coi, Bix, A16): only as a whole fragment, or as the head of a
    #     fragment whose remainder is a venue descriptor (/coirestaurant)
    #   - longer: the whole fragment, with little else in the slug
    if len(words) == 1:
        w = words[0]
        # Some single words are so common in restaurant names that matching one
        # identifies nothing: "The Bird" matched both state-bird-provisions and
        # social-bird, which are other restaurants. These require a descriptor
        # or a longer fragment, never a bare word match.
        if w in _TOO_GENERIC_ALONE:
            return False
        if w in sig:
            others = [b for b in sig if b != w]
            if len(w) <= 5:
                return True                   # exact fragment, e.g. /r/coi
            return len(others) <= 1
        if len(w) <= 5:
            return any(b.startswith(w) and b[len(w):] in _SLUG_TAILS
                       for b in sig)          # /coirestaurant
        return False

    # 1. consecutive run of significant fragments: /r/per-se, /r/rich-table,
    #    /r/sons-and-daughters (with "and" dropped from the path side too)
    n = len(words)
    for i in range(len(sig) - n + 1):
        if sig[i:i + n] == words:
            return True

    # 2. the name run together, either in one fragment (/zunicafe) or across
    #    adjacent fragments (/mister-jius -> "misterjius"). The match must be
    #    followed only by a venue descriptor or a possessive "s", which is what
    #    rejects "coin"+"op" for Coi.
    squash = "".join(words)
    for i in range(len(sig)):
        acc = ""
        for j in range(i, len(sig)):
            acc += sig[j]
            if acc == squash or (len(acc) > len(squash) and acc.startswith(squash)):
                tail = acc[len(squash):]
                if tail == "" or tail == "s" or tail in _SLUG_TAILS:
                    return True
            if len(acc) > len(squash) + 24:
                break                     # stop runaway concatenation
    return False


# TLDs that name a company rather than a place. A domain ending in one of
# these is a business registry entry, not a restaurant's own site even when
# the label matches the venue exactly (haven.inc).
_COMPANY_TLDS = {"inc", "llc", "corp", "company", "ltd", "gmbh", "ai", "io",
                 "app", "dev", "tech", "finance", "capital", "ventures"}

# Words that look like a venue descriptor but name a different KIND of
# business. "plumorganicbeauty.com" is name + "beauty": a salon, not a
# restaurant. These never count as the suffix that makes a domain the venue's.
_NON_VENUE_TAILS = {
    "beauty", "salon", "spa", "organic", "cosmetics", "skincare", "nails",
    "hair", "fitness", "gym", "hotel", "motel", "inn", "realty", "properties",
    "law", "legal", "dental", "medical", "pharmacy", "clinic", "vet",
    "bank", "finance", "capital", "insurance", "software", "labs", "studio",
}

# Suffixes a venue appends to its own name in a URL. "coirestaurant" splits as
# coi + restaurant and is the venue; "coinop" splits as coi + nop and is not.
_SLUG_TAILS = {
    "", "sf", "sfo", "sanfrancisco", "restaurant", "restaurants", "resto",
    "cafe", "bar", "kitchen", "bistro", "grill", "pizza", "sushi", "taqueria",
    "group", "hospitality", "dining", "eatery", "food", "foods", "noodle",
    "noodles", "ramen", "bakery", "brasserie", "trattoria", "osteria", "wine",
    "steak", "steakhouse", "house", "and", "the", "co", "inc", "llc",
}


def _booking_city_mismatch(path, query=""):
    """Does the URL name a city other than the Bay Area?

    Resy and OpenTable put the city in the path
    (`/cities/dallas-fort-worth-tx/venues/...`). Matching words alone let
    "The Beehive" resolve to a Dallas restaurant and "Ubuntu" to a café in San
    Juan Capistrano. The corpus is San Francisco, so a booking page naming
    another metro is the wrong restaurant no matter how well the name fits.
    """
    low = (path + "?" + (query or "")).lower()
    for city in _OTHER_CITIES:
        if city in low:
            return True
    return False


# Single words that appear in so many restaurant names that matching one proves
# nothing. "The Bird" resolved to State Bird Provisions and to Social Bird.
_TOO_GENERIC_ALONE = {
    "bird", "bar", "cafe", "grill", "kitchen", "house", "table", "spoon",
    "fork", "salt", "stone", "garden", "market", "corner", "street", "park",
    "blue", "red", "black", "white", "gold", "green", "star", "sun", "moon",
    "fire", "smoke", "vine", "oak", "bay", "sea", "river", "farm",
}

# Metros that appear in Resy/OpenTable URLs and are far outside this corpus.
# Deliberately NOT a complete list and deliberately excludes the Bay Area and
# nearby wine country: the graph already carries non-SF venues (French
# Laundry, Meadowood, Gramercy Tavern) as legitimate nodes, so "not San
# Francisco" is not by itself wrong.
_OTHER_CITIES = (
    "dallas", "fort-worth", "houston", "austin", "chicago", "boston",
    "new-york", "brooklyn", "seattle", "denver", "atlanta", "miami",
    "philadelphia", "washington-dc", "las-vegas", "los-angeles",
    "san-diego", "san-juan", "toronto", "vancouver", "london", "paris",
)


def find_booking_links(venue):
    """Reservation-platform URLs SERP returns for this venue.

    Verified to be the VENUE's page on that platform, not the platform's
    homepage: a "Book on Resy" link that lands on resy.com is a broken promise,
    and a link to a similarly-named restaurant is worse.
    """
    from src.brightdata import serp
    out = {}
    for platform, host in (("resy", "resy.com"), ("opentable", "opentable.com"),
                           ("tock", "exploretock.com")):
        try:
            for r in serp(f"{venue} San Francisco {platform}", num=10):
                h = _host(r["url"]).rstrip(".")
                if not h:
                    continue
                # EXACT platform domain or an allowed subdomain of it. A
                # substring test accepted `fake-resy.com/rich-table`, which
                # passes both the host and venue-path checks and would be saved
                # as a Resy link. `www` is the only subdomain worth keeping;
                # blog/help/support are editorial or support pages, not booking.
                sub = ""
                if h == host:
                    pass
                elif h.endswith("." + host):
                    sub = h[:-len(host) - 1]
                    if sub != "www":
                        continue
                else:
                    continue
                parts = urllib.parse.urlsplit(r["url"])
                path = urllib.parse.unquote(parts.path).lower()
                # A SEARCH or editorial page is not a booking page:
                # resy.com/city/san-francisco?query=Rich%20Table passed the old
                # whole-URL check and would have been offered as "Book on Resy".
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
                # Right name, wrong city: "The Beehive" resolved to a Dallas
                # restaurant, "Ubuntu" to a café in San Juan Capistrano.
                if _booking_city_mismatch(path, parts.query):
                    continue
                if _slug_names_venue(path, venue):
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
            # Attribute values arrive entity-encoded. `&amp;` in a query string
            # changes the parameter name, so the download would request a
            # different image — or 404 on a URL that plainly works in a browser.
            u = html_module.unescape(u)
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
                                        "avatar", "badge", "dummy")):
                continue
            # A declared lead image is not automatically a photograph of the
            # place. Real captures: a slider plugin's bundled `dummy.png`
            # (RevSlider) and a tracker's `c3po.jpg` (metricool) were both
            # stored as high-confidence venue photos.
            if any(x in u.lower() for x in _NON_PHOTO_PATH_PARTS):
                continue
            return u
    return None


def _domain_verdict(url, venue):
    """True / False / None — does this domain settle the venue's identity?

    True  — the domain is unmistakably the venue's own: name + a venue
            descriptor (`azizasf.com`, `flourandwater.com`,
            `sonsanddaughterssf.com`).
    False — the domain says this is a DIFFERENT kind of business carrying the
            same name: `plumorganicbeauty.com` (a salon — "beauty" is not a
            venue word) or `haven.inc` (a company TLD).
    None  — the domain tells us nothing either way, so the caller falls back
            to the page's own text.

    A bare name with NO descriptor (`parktavern.net`, `coi.com`, `benu.com`)
    is deliberately None, not True. Any business anywhere can own its own name
    on a generic TLD — parktavern.net is a bowling alley in Minnesota — so an
    exact match alone proves nothing about WHICH Park Tavern. Those venues get
    resolved by the page's locality instead.
    """
    h = _host(url)
    if not h:
        return None
    parts = h.split(".")
    if len(parts) < 2:
        return None
    label = parts[-2].replace("-", "")
    tld = parts[-1].lower()
    words = [w for w in re.split(r"[^a-z0-9]+", venue.lower()) if w]
    if not words or not label:
        return None
    # "&" and "+" are written as "and" in a domain far more often than dropped:
    # "Sons & Daughters" -> sonsanddaughterssf.com, "Flour + Water" ->
    # flourandwater.com.
    forms = {"".join(words)}
    spelled = venue.lower().replace("&", "and").replace("+", "and")
    forms.add("".join(re.split(r"[^a-z0-9]+", spelled)))
    for squash in filter(None, forms):
        if label == squash:
            # A bare name proves little: any business owns its own name, so
            # parktavern.net is a Minnesota bowling alley and flourandwater.com
            # could be a flour company. A company TLD is a definite no; a
            # generic one is inconclusive and the page has to corroborate.
            # Trying to separate "distinctive" multi-word names from generic
            # ones here was a guess — "Park Tavern" and "Flour + Water" are
            # structurally identical — so it is not attempted.
            return False if tld in _COMPANY_TLDS else None
        if not label.startswith(squash):
            continue
        tail = label[len(squash):]
        if tail in _NON_VENUE_TAILS or any(t in tail for t in _NON_VENUE_TAILS):
            return False                # name + a different kind of business
        if tail in _SLUG_TAILS:
            return True                 # name + a venue descriptor
        return None                     # unrecognised: defer to the page
    return None


def _domain_names_venue(url, venue):
    """Does the domain itself prove ownership? (True only; see verdict above.)"""
    return _domain_verdict(url, venue) is True


# URL path fragments that mark a NON-photograph: theme/plugin bulk assets and
# analytics trackers. A venue page can declare any of these as its lead image —
# a slider plugin's own `dummy.png`, a metricool tracker pixel — and none of
# them is a picture of the restaurant.
_NON_PHOTO_PATH_PARTS = (
    "/plugins/", "/wp-content/plugins/", "/assets/assets/",
    "/tracker.", "tracker.metricool.", "/pixel.", "analytics.",
)


def _page_names_venue(html, venue, url=None):
    """Does this page plausibly belong to `venue`?

    Identity needs more than the name appearing somewhere. Recovered results
    included `plumorganicbeauty.com` for Plum (a beauty salon, in San
    Francisco), `haven.inc` for Haven ("a bank account for art"), and a Park
    Tavern in St. Louis Park, Minnesota. Every one contains the venue's name,
    so a name-only test passes them all and the dossier gets a stranger's
    photograph.

    So: the NAME must appear, and identity must be corroborated by either the
    domain shape (name + venue descriptor) or an explicit local signal in the
    text. JS-shell pages have no text, which is why the domain check leads.
    """
    n = norm(venue)
    if not n:
        return False
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)

    # Short names need a TOKEN match, not a substring. norm() only strips
    # punctuation, so "Coi" would match inside "coin-op", "coincidence", or
    # "Coin-Op Restaurant" — and the venue would be given a stranger's page.
    # A 4+ character name keeps the lenient test, where accidental substrings
    # are vanishingly rare and markup-heavy pages would otherwise fail.
    if len(n) < 4:
        toks = re.split(r"[^a-z0-9]+", text.lower())
        named = n in toks
    else:
        named = n in norm(text)
    if not named:
        return False
    if not url:
        # No URL to judge: the name match is all the evidence there is. Used by
        # social-profile checks, which already opened a confirmed handle.
        return True
    verdict = _domain_verdict(url, venue)
    if verdict is not None:
        return verdict                  # the domain settles it, either way
    # Domain tells us nothing (a group site, an unrecognised shape). The page's
    # own locality has to carry it, and a bare name in an <h1> does not.
    return _reads_as_sf(text)


# A venue's own site says where it is. Anything claiming to be one of these
# venues without this signal is a namesake in another city.
_SF_TOKENS = ("san francisco", "sanfrancisco", "bay area", "oakland",
              "berkeley", "mission district", "soma", "hayes valley",
              "nob hill", "north beach", "financial district", "marina",
              "richmond", "sunset", "castro", "potrero", "dogpatch",
              "tenderloin", "japantown", "chinatown", "presidio",
              "embarcadero", "union square", "fidi",
              # A group site covering San Francisco often names the state, not
              # the city (theminagroup.com says "California"). Narrower would
              # reject real venues; the name still has to match, so this is
              # only the corroborating signal, not the identity claim.
              "california", ", ca ", "ca 9")


def _reads_as_sf(text):
    """Locality gate: does the page situate the venue in the Bay Area?

    Deliberately requires a place NAME, not the bare token "sf" — "sf" appears
    inside countless words and abbreviations and would pass everything.
    """
    low = " " + re.sub(r"\s+", " ", text.lower()) + " "
    return any(t in low for t in _SF_TOKENS)


def tier_website(venue, known_website=None, timeout=15, broken_host=None):
    """The venue's own page, fetched only from a public address, redirects
    checked hop by hop. Returns None unless the page both names the venue and
    declares an image.

    `broken_host` names the single host whose incomplete TLS chain we accept,
    for a site recorded in venue_sites.json. It is never inferred from the
    response — a caller has to say so — and it does not travel to redirect
    targets or image hosts.
    """
    for url in _candidate_sites(venue, known_website)[0]:
        r = safe_get(url, timeout=timeout, allow_broken_chain_for=broken_host)
        if r is None or r.status_code != 200:
            continue
        if not _page_names_venue(r.text, venue, url=r.url or url):
            continue                          # someone else's site
        img = _og_image(r.text, base_url=r.url or url)
        if img:
            return {"url": img, "source": "venue-website", "site": r.url or url,
                    "confidence": "high",
                    "evidence": "declared image on the venue's own site"}
    return None


def download_image(url, venue_key, timeout=25, broken_host=None):
    """Fetch an image once and store it locally. Returns a relative path or None.

    This is the half that makes "lookup only" true: a remote URL in the cache
    would still be a hotlink, which is the exact thing this module exists to
    remove. Nothing is served from a third-party CDN at render time.

    `broken_host` mirrors safe_get's: a host that omits its TLS intermediate
    fails on the image request too. It applies only to that host, so an image
    served from a different CDN keeps full certificate checks.
    """
    if not url or not _url_is_public(url):
        return None
    r = safe_get(url, timeout=timeout, allow_broken_chain_for=broken_host)
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

def tier_social(venue, known_website=None, timeout=15, broken_host=None):
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
    r = safe_get(known_website, timeout=timeout, allow_broken_chain_for=broken_host)
    if r is None or r.status_code != 200:
        return None
    m = re.search(r'(instagram|facebook)\.com/([A-Za-z0-9_.]+)', r.text)
    if not m:
        return None                       # no handle: do not guess one
    platform, handle = m.group(1), m.group(2).rstrip(".")
    if handle in ("p", "reel", "explore", "accounts", "share", "login"):
        return None                       # a link path, not a profile
    # Fetch the profile on the platform we actually saw. Opening the handle on
    # Instagram because the link said Facebook proved nothing: @handle on
    # Instagram can easily be somebody else, and its photo would then be
    # attached to this restaurant with no name check.
    profile = f"https://www.{platform}.com/{handle}/"
    pr = safe_get(profile, timeout=timeout)
    if pr is None or pr.status_code != 200:
        return None
    # The profile has to name the venue before its picture is the venue's.
    # Domain verdict is deliberately not applied: a social profile lives on
    # instagram.com / facebook.com, which is never name-shaped, and the handle
    # itself was read from the venue's confirmed website.
    if not _page_names_venue(pr.text, venue):
        return None
    img = _og_image(pr.text, base_url=pr.url or profile)
    if not img:
        return None
    return {"url": img, "source": "venue-social", "site": f"{platform}.com",
            "confidence": "low", "handle": handle,
            "evidence": "profile image from a handle linked by the venue's own site"}


# ── driver ──────────────────────────────────────────────────────────────────

def resolve_venue(venue, token=None, known_website=None, use_serp=True,
                  broken_host=None):
    """Run the tiers in order. Returns (record, status).

    status is "found", "absent" or "failed". Only "absent" may be cached as a
    negative result; "failed" must stay eligible so an outage does not become a
    permanent hole in the cache.

    A tier only COUNTED once its bytes were downloaded. Previously the website
    tier returned a record as soon as it found a declared image URL, so a 403,
    a timeout, or a non-image response skipped the social and Mapbox tiers and
    then cleared `url` at the end — finishing with no photo even though another
    tier could have supplied one.
    """
    site = known_website
    status = "absent"
    booking = {}
    if use_serp and not site:
        site, status = find_official_site(venue)
        if status == "failed":
            return None, "failed"
    # Booking discovery needs only the venue name, so it must not be gated on
    # finding a website. A venue whose only web presence is its reservation
    # page has no official site by definition (those platforms are excluded
    # from _is_official), and was therefore never checked for a booking link.
    if use_serp:
        booking = find_booking_links(venue)

    def own(img):
        """Download the tier's image. None unless we hold the bytes."""
        if not img or not img.get("url"):
            return None
        url = str(img["url"])
        if not url.startswith(("http://", "https://")):
            return img                    # already a local path
        local = download_image(url, venue, broken_host=broken_host)
        if not local:
            return None                   # could not own it: try the next tier
        out = dict(img)
        out["remote"] = url
        out["url"] = local
        return out

    img = None
    if site:
        img = own(tier_website(venue, site, broken_host=broken_host))
    if not img:
        img = own(tier_social(venue, site, broken_host=broken_host))
    if not img and token:
        img = own(tier_mapbox(venue, token))

    if not img and not site and not booking:
        return None, "absent"

    out = dict(img or {"url": None, "source": None})
    out["site"] = site
    if booking:
        out["booking"] = booking
    return out, "found"


def _distinct_field(field, distinct_values, es, field_names=None):
    """Values of `field` from whichever index shape this cluster has.

    Lives at module level, not nested in main(), so tests can exercise the REAL
    function. The first version was defined inside main() and the tests
    reimplemented it — reverting the fix would have left them green.

    Only FIELD-SHAPE failures may be swallowed. An unreachable cluster or a
    rejected credential must stop the run: swallowing those made `main`
    report "0 venues" and exit 0, which reads exactly like "nothing to do".
    """
    names = field_names or (field, field + ".keyword")
    last = None
    # A read that COMPLETES is an answer, even an empty one. Raising an earlier
    # shape error then would abort the run before the other field was read —
    # an empty `from_venue` legitimately returns an empty set, and that must
    # not be mistaken for "both shapes failed".
    answered = False
    for name in names:
        try:
            vals = distinct_values(es, name)
        except Exception as e:            # noqa: BLE001 — narrowed just below
            if not _is_field_shape_error(e):
                raise
            last = e
            continue                      # wrong shape for this cluster
        answered = True                   # this shape works, even if empty
        if vals:
            return vals
    if not answered and last:
        raise last                        # neither shape could be read
    return set()


def distinct_venues(es, distinct_values):
    """Every venue name the lineage graph mentions, from either index shape."""
    return (_distinct_field("to_venue", distinct_values, es)
            | _distinct_field("from_venue", distinct_values, es))


def _is_field_shape_error(exc):
    """True only for "this cluster maps the field differently than I assumed".

    These are the errors a wrong field NAME or TYPE produces, and they are
    recoverable by trying the other shape. A connection failure, a timeout, or
    a 401/403 is NOT this: those mean the run cannot do its job, and treating
    them as "no venues" would report success while resolving nothing.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    if "fielddata" in text:
        return True                       # text field, needs .keyword
    if "unknown field" in text or "no mapping found" in text:
        return True                       # .keyword absent on a fresh index
    if "illegal_argument_exception" in text or "query_shard_exception" in text:
        return True
    if "search_phase_execution_exception" in text:
        # ES wraps a per-shard mapping failure in this; unwrap on the cause text
        return any(k in text for k in ("fielddata", "unknown field",
                                       "no mapping", "not aggregatable"))
    return False


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
        # int(), not a truthiness check: `if limit:` treated 0 as "no limit" and
        # started the full 4,754-venue run when the caller asked for none.
        limit = max(0, int(argv[argv.index("--limit") + 1]))

    # Venues worth resolving: those the lineage graph actually names.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ui_server_img", os.path.join(BASE, "ui", "server.py"))
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    from src.es import make_client
    es = make_client()

    # to_venue / from_venue have TWO shapes in the wild and neither read works
    # on both:
    #   - an index built by ensure_index: a plain keyword field, so `.keyword`
    #     does not exist and aggregating it returns nothing;
    #   - the legacy live index: a text field WITH a `.keyword` subfield, where
    #     aggregating the bare field raises "Fielddata is disabled".
    # Try the mapped field, and fall back to the subfield on either an
    # exception or an empty result. Getting this wrong is silent in one
    # direction (zero venues, "resolved successfully") and fatal in the other.
    raw = distinct_venues(es, ui._distinct_values)
    venues = sorted({v for v in raw if v and not ui._is_junk_venue(v)})

    # curated websites, where we have them
    sites = {}
    gp = os.path.join(BASE, "ui", "venues_geo.json")
    if os.path.exists(gp):
        for v in json.load(open(gp)).get("venues", []):
            if v.get("website"):
                sites[v["name"].lower()] = v["website"]

    # Human verdicts (ui/venue_sites.json) outrank SERP. For a closed
    # restaurant SERP returns dead domains, lookalikes and directory pages, and
    # retrying it forever turns "this place is gone" into "no image yet".
    closed, decided_site, broken = set(), {}, set()
    sp = os.path.join(BASE, "ui", "venue_sites.json")
    if os.path.exists(sp):
        verdicts = json.load(open(sp))
        closed = set(verdicts.get("closed") or {})
        decided_site = dict(verdicts.get("website") or {})
        broken = set(verdicts.get("broken_tls_chain") or {})

    cache = load_cache()

    def superseded(k, entry):
        """Does the cache disagree with the current human verdict?

        A cached answer normally wins, so a *new or corrected* verdict had no
        way in: adding coirestaurant.com for a venue cached as absent left the
        absence in place on every later run. A changed verdict reopens the
        venue.
        """
        want = decided_site.get(k)
        if want and (entry.get("site") or "") != want:
            return True
        return False

    # A "failed" entry is retried on the next run; only a real answer is final.
    # A human verdict is final too: closed venues are never re-probed.
    todo = [v for v in venues
            if norm(v) not in closed
            and (norm(v) not in cache
                 or cache[norm(v)].get("status") == "failed"
                 or superseded(norm(v), cache[norm(v)]))]
    if limit is not None:
        todo = todo[:limit]

    print(f"{len(venues)} venue names · {len(cache)} cached · "
          f"{len(closed)} closed by verdict · resolving {len(todo)}")

    # Each venue costs several network calls (SERP, page, image). Serially with
    # a sleep between them the full corpus is hours of wall clock, so fan out.
    # Concurrency is deliberate but modest: the SERP zone returns empty bodies
    # under load, and a burst just converts into retries.
    workers = 1
    for flag in ("--workers", "-j"):
        if flag in argv:
            workers = max(1, int(argv[argv.index(flag) + 1]))

    failed = []

    def resolve_one(v):
        k = norm(v)
        site = decided_site.get(k) or sites.get(v.lower())
        # Pass the HOST to relax, not a boolean: safe_get compares it against
        # the host actually being fetched, so redirect targets and image CDNs
        # keep full certificate verification.
        broken_host = _host(site) if (k in broken and site) else None
        try:
            r, status = resolve_venue(v, token=token, known_website=site,
                                      broken_host=broken_host)
        except Exception as e:            # one venue must not kill the run
            # Recovering is right; swallowing silently is not. A disk error or
            # a code fault would otherwise fail hundreds of venues while the
            # run printed only progress and exited 0.
            return v, None, "failed", (type(e).__name__, str(e)[:160])
        return v, r, status, None

    hits, done = 0, 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(resolve_one, v): v for v in todo}
        for fut in as_completed(futures):
            v, r, status, err = fut.result()
            k = norm(v)
            if err:
                failed.append((v, err))
            if status == "failed":
                # do NOT cache: an outage must not look like "this venue has no site"
                cache[k] = {"url": None, "source": None, "status": "failed"}
            else:
                cache[k] = dict(r or {"url": None, "source": None}, status=status)
                if k in decided_site:
                    cache[k]["site"] = decided_site[k]
                    cache[k]["site_source"] = "verdict"
                hits += 1 if (r and r.get("url")) else 0
            done += 1
            # Cache writes stay on this thread: the workers only return records.
            if done % 25 == 0 or done == len(todo):
                save_cache(cache)
                print(f"  [{done}/{len(todo)}] resolved {hits} "
                      f"({hits/max(done,1)*100:.0f}%)", flush=True)
    save_cache(cache)

    found = sum(1 for x in cache.values() if x.get("url"))
    print(f"done: {found}/{len(cache)} venues have an image "
          f"({found/max(len(cache),1)*100:.0f}%) → {CACHE}")
    if failed:
        # Loud, and non-zero exit: a run that failed venues silently looked
        # identical to a clean one.
        print(f"\n{len(failed)} venues raised while resolving:", flush=True)
        for v, (kind, msg) in failed[:20]:
            print(f"  {v[:40]:40} {kind}: {msg}")
        if len(failed) > 20:
            print(f"  ... and {len(failed) - 20} more")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
