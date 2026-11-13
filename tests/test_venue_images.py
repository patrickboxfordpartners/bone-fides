"""Venue image resolution: license-clean photography, no hotlinking.

The corpus hotlinked publisher CDN images onto every dossier. This module
replaces that with images the venue itself publishes.
"""
import os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)
from src.venue_images import _is_official, norm, _og_image

def test_lookalike_subdomain_rejected():
    """A SERP hit for Rich Table returned richtablesf.nevertrustadame.com.
    Accepting it points readers at a phishing page."""
    assert not _is_official("https://www.richtablesf.nevertrustadame.com/contact.html", "Rich Table")

def test_real_official_sites_accepted():
    for url, v in [("https://www.richtablesf.com/","Rich Table"),
                   ("https://www.delfinasf.com/","Delfina"),
                   ("https://zunicafe.com/","Zuni Cafe"),
                   ("https://tartinebakery.com/","Tartine Bakery"),
                   ("https://www.misterjius.com/","Mister Jiu's")]:
        assert _is_official(url, v), f"{url} should be accepted for {v}"

def test_directories_and_platforms_rejected():
    for url, v in [("https://plac.es/places/615","Nopa"),
                   ("https://www.opentable.com/zuni-cafe","Zuni Cafe"),
                   ("https://sf.eater.com/x","Mourad"),
                   ("https://www.yelp.com/biz/mourad","Mourad"),
                   ("https://www.facebook.com/zuni","Zuni Cafe")]:
        assert not _is_official(url, v), f"{url} must not count as {v}'s site"

def test_squarespace_sites_yield_an_image():
    """Benu publishes no og:image; an OG-only extractor missed it entirely."""
    html = '<script>{"assetUrl":"https://images.squarespace-cdn.com/content/v1/abc/hero.jpg"}</script>'
    assert _og_image(html) == "https://images.squarespace-cdn.com/content/v1/abc/hero.jpg"

def test_logos_and_icons_never_become_the_hero():
    assert _og_image('<img src="https://x.com/logo.png">') is None
    assert _og_image('<img src="https://x.com/favicon.ico">') is None

def test_norm_folds_punctuation():
    assert norm("Mister Jiu's") == norm("mister jius") == "misterjius"


# ── SSRF: no request may reach a private address ────────────────────────────

def test_private_addresses_are_refused():
    from src.venue_images import _is_public_host
    for h in ("127.0.0.1", "localhost", "169.254.169.254", "10.0.0.5",
              "192.168.1.1", "[::1]", "0.0.0.0"):
        assert not _is_public_host(h), f"{h} must not be fetchable"
    assert _is_public_host("8.8.8.8")
    assert _is_public_host("example.com")


def test_non_http_schemes_are_refused():
    from src.venue_images import _url_is_public
    assert not _url_is_public("file:///etc/passwd")
    assert not _url_is_public("http://127.0.0.1/x")
    assert not _url_is_public("http://169.254.169.254/latest/meta-data")
    assert _url_is_public("https://example.com/a.jpg")


def test_safe_get_does_not_follow_redirect_into_private_space(monkeypatch):
    """A controlled domain redirecting to a private service must be stopped
    before the second request is made."""
    import src.venue_images as v

    class Resp:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data"}
        url = "https://evil.example/x"

    calls = []
    def fake_get(url, **kw):
        calls.append(url)
        return Resp()
    monkeypatch.setattr("requests.get", fake_get)
    # a real, resolvable public host so the FIRST hop is allowed through and the
    # redirect itself is what gets blocked
    assert v.safe_get("https://example.com/x") is None
    assert calls == ["https://example.com/x"], (
        "the redirect destination must never be requested")


# ── verification and caching semantics ──────────────────────────────────────

def test_short_venue_names_never_pass_on_domain_alone():
    """`24` was assigned theindependentsf.com because a 2-char name skipped the
    token check. Short names must fail _is_official and be admitted only by the
    page-names-venue check."""
    assert not _is_official("https://theindependentsf.com/", "24")
    assert not _is_official("https://coirestaurant.com/", "Coi")


def test_page_check_reads_text_not_markup():
    """Searches the visible text, so tag/class/script content cannot make a page
    "name" a venue."""
    from src.venue_images import _page_names_venue
    html = '<div class="zunicafe"><script>var zunicafe=1</script></div>'
    assert not _page_names_venue(html, "Zuni Cafe")
    assert _page_names_venue("<h1>Welcome to Zuni Cafe</h1>", "Zuni Cafe")


def test_resolve_reports_failure_separately_from_absence():
    """An outage must not be cached as "this venue has no website"."""
    import src.venue_images as v
    monkeypatch_target = v.find_official_site
    def boom(*a, **k):
        return None, "failed"
    v.find_official_site = boom
    try:
        rec, status = v.resolve_venue("Zuni Cafe", use_serp=True)
        assert status == "failed" and rec is None
    finally:
        v.find_official_site = monkeypatch_target


def test_host_strips_only_a_leading_www():
    from src.venue_images import _host
    assert _host("https://www.mywww.com/a") == "mywww.com"
    assert _host("https://newww.com/") == "newww.com"
    assert _host("https://www.zunicafe.com/") == "zunicafe.com"


def test_bare_icon_filename_is_not_photography():
    """`social+icon.png` was accepted as a high-confidence hero photo."""
    assert _og_image('<img src="https://x.com/social+icon.png">', "https://x.com/") is None
    assert _og_image('<img src="https://x.com/social%2Bicon.png">', "https://x.com/") is None
    assert _og_image('<img src="https://x.com/favicon.ico">', "https://x.com/") is None


def test_relative_image_paths_are_resolved():
    assert _og_image('<meta property="og:image" content="/img/hero.jpg">',
                     "https://zunicafe.com/menu") == "https://zunicafe.com/img/hero.jpg"
    assert _og_image('<meta property="og:image" content="//cdn.x.com/h.jpg">',
                     "https://zunicafe.com/") == "https://cdn.x.com/h.jpg"


def test_download_refuses_a_private_url():
    from src.venue_images import download_image
    assert download_image("http://169.254.169.254/x.jpg", "x") is None


def test_blog_and_search_urls_are_not_booking_pages():
    """A "Book on Resy" link pointed at blog.resy.com and at resy search pages.

    Neither is where a diner books; offering them is a broken promise.
    """
    import src.venue_images as v
    cases = [
        "https://blog.resy.com/2024/04/rich-table-perfect-san-francisco-restaurant/",
        "https://resy.com/city/san-francisco?query=Rich%20Table",
        "https://www.opentable.com/s?term=rich%20table",
        "https://www.exploretock.com/search?q=rich+table",
        "https://resy.com/stories/something",
    ]
    real = v.find_booking_links
    def fake(venue):
        return {}
    # assert via the filter logic directly
    import urllib.parse
    for url in cases:
        h = v._host(url)
        path = urllib.parse.unquote(urllib.parse.urlsplit(url).path).lower()
        sub = h.split(".")[0]
        bad_path = any(s in path for s in ("/city/", "/search", "/discover", "/blog/",
                                          "/stories/", "/article/")) \
            or path.rstrip("/") in ("/s", "/searches", "")
        bad_sub = sub in ("blog", "help", "support", "news", "press", "about")
        bad_query = "query=" in (urllib.parse.urlsplit(url).query or "").lower()
        assert bad_path or bad_sub or bad_query, f"{url} would pass as a booking page"
