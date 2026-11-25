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


def _fixed_dns(monkeypatch, mapping):
    """Answer getaddrinfo from a fixed table so these tests never need DNS.

    They used real lookups for example.com, which made them fail on a machine
    with no resolver even though the code under test was fine.
    """
    import socket as _socket

    def fake(host, port, *a, **kw):
        addr = mapping.get(host)
        if addr is None:
            raise _socket.gaierror("no such host (test table)")
        return [(2, 1, 6, "", (addr, 0))]
    monkeypatch.setattr(_socket, "getaddrinfo", fake)


def test_public_host_is_accepted(monkeypatch):
    from src.venue_images import _is_public_host
    _fixed_dns(monkeypatch, {"example.com": "93.184.216.34"})
    assert _is_public_host("example.com")


def test_overlong_dns_label_is_refused_not_raised(monkeypatch):
    """A DNS label over 63 chars makes the idna codec raise UnicodeEncodeError,
    not gaierror. The host cannot resolve, so it must be refused — not crash
    the venue's whole resolution run (Boka did exactly that on the live corpus).
    """
    import socket as _socket
    import src.venue_images as v

    def boom(host, *a, **kw):
        raise UnicodeEncodeError("idna", host, 0, 70, "label too long")
    monkeypatch.setattr(_socket, "getaddrinfo", boom)

    assert not v._is_public_host("a" * 70 + ".com")
    assert not v._url_is_public("https://" + "a" * 70 + ".com/x.jpg")


def test_non_http_schemes_are_refused(monkeypatch):
    from src.venue_images import _url_is_public
    _fixed_dns(monkeypatch, {"example.com": "93.184.216.34"})
    assert not _url_is_public("file:///etc/passwd")
    assert not _url_is_public("http://127.0.0.1/x")
    assert not _url_is_public("http://169.254.169.254/latest/meta-data")
    assert _url_is_public("https://example.com/a.jpg")


def test_safe_get_does_not_follow_redirect_into_private_space(monkeypatch):
    """A controlled domain redirecting to a private service must be stopped
    before the second request is made."""
    import src.venue_images as v
    _fixed_dns(monkeypatch, {"example.com": "93.184.216.34"})

    class Resp:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data"}
        url = "https://evil.example/x"

    calls = []
    def fake_get(url, **kw):
        calls.append(url)
        return Resp()
    monkeypatch.setattr("requests.get", fake_get)
    # the FIRST hop is allowed through, so the redirect itself is what gets
    # blocked — that is the behaviour under test
    assert v.safe_get("https://example.com/x") is None
    assert calls == ["https://example.com/x"], (
        "the redirect destination must never be requested")


# ── verification and caching semantics ──────────────────────────────────────

def test_short_venue_names_never_pass_on_domain_alone():
    """A 2-char name skipped the token check entirely, so `24` was assigned
    theindependentsf.com. A short name is admitted on the domain only when it
    LEADS the registered domain (coirestaurant.com for Coi); anything else has
    to be proven by the page-names-the-venue check.

    Rejecting every short-name hit outright — the previous behaviour — meant
    coirestaurant.com was never even tried and got cached as absent forever.
    """
    assert not _is_official("https://theindependentsf.com/", "24")
    assert not _is_official("https://coinoprestaurant.com/", "Coi")
    assert not _is_official("https://www.youtube.com/watch?v=coi", "Coi")
    # name-led domains are candidates; the page check still decides
    assert _is_official("https://coirestaurant.com/", "Coi")
    assert _is_official("https://www.a16pizza.com/", "A16")


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


def test_blog_and_search_urls_are_not_booking_pages(monkeypatch):
    """A "Book on Resy" link pointed at blog.resy.com and at resy search pages.

    Neither is where a diner books; offering them is a broken promise. This
    drives the REAL find_booking_links with a stubbed SERP — the previous
    version re-implemented the filters beside it, so it still passed if the
    production function accepted every bad URL.
    """
    import src.search as bd
    import src.venue_images as v

    bad = [
        "https://blog.resy.com/2024/04/rich-table-perfect-san-francisco-restaurant/",
        "https://resy.com/city/san-francisco?query=Rich%20Table",
        "https://www.opentable.com/s?term=rich%20table",
        "https://www.exploretock.com/search?q=rich+table",
        "https://resy.com/stories/something",
    ]
    monkeypatch.setattr(bd, "search", lambda q, num=10: [{"url": u, "title": ""} for u in bad])
    assert v.find_booking_links("Rich Table") == {}


def test_lookalike_platform_domains_are_not_booking_links(monkeypatch):
    """`fake-resy.com/rich-table` passed a substring host test and was saved as
    the Resy link for Rich Table."""
    import src.search as bd
    import src.venue_images as v

    bad = [
        "https://fake-resy.com/rich-table",
        "https://notopentable.com/r/rich-table-san-francisco",
        "https://resy.com.evil.example/rich-table",
    ]
    monkeypatch.setattr(bd, "search", lambda q, num=10: [{"url": u, "title": ""} for u in bad])
    assert v.find_booking_links("Rich Table") == {}


def test_booking_link_must_match_a_slug_boundary(monkeypatch):
    """`coi` sits inside `coin-op`, so Coi was handed Coin-Op's booking page."""
    import src.search as bd
    import src.venue_images as v

    monkeypatch.setattr(bd, "search",
                        lambda q, num=10: [{"url": "https://www.opentable.com/r/coin-op-san-francisco",
                                            "title": ""}])
    assert v.find_booking_links("Coi") == {}

    # the real page still resolves
    monkeypatch.setattr(bd, "search",
                        lambda q, num=10: [{"url": "https://www.opentable.com/r/coi-san-francisco",
                                            "title": ""}])
    assert v.find_booking_links("Coi").get("opentable") == \
        "https://www.opentable.com/r/coi-san-francisco"


# ── PR #12 findings: security and fallback semantics ─────────────────────────

def test_tls_exception_is_scoped_to_one_host(monkeypatch):
    """The Commis exception must not relax verification anywhere else.

    safe_get took a boolean, so the disabled check applied to every redirect
    hop and to any image CDN — an attacker between us and those hosts could
    have supplied a false venue photo.
    """
    import src.venue_images as v
    monkeypatch.setattr(v, "_url_is_public", lambda u: True)

    seen = []
    def fake_get(url, **kw):
        seen.append((url, kw.get("verify", True)))
        if kw.get("verify") is False:
            raise AssertionError(f"certificate checks were disabled for {url}")
        raise RuntimeError("CERTIFICATE_VERIFY_FAILED: unable to verify")
    monkeypatch.setattr("requests.get", fake_get)

    # a different host must never be relaxed, even with the flag set
    assert v.safe_get("https://cdn.example.net/img.jpg",
                      allow_broken_chain_for="commisrestaurant.com") is None
    assert all(verify is not False for _, verify in seen)


def test_tls_exception_applies_to_the_named_host(monkeypatch):
    import src.venue_images as v
    monkeypatch.setattr(v, "_url_is_public", lambda u: True)

    class Ok:
        status_code = 200
        headers = {}
        url = "https://commisrestaurant.com/"
        text = "<h1>Commis</h1>"

    calls = []
    def fake_get(url, **kw):
        calls.append(kw.get("verify", True))
        if kw.get("verify") is False:
            return Ok()
        raise RuntimeError("CERTIFICATE_VERIFY_FAILED")
    monkeypatch.setattr("requests.get", fake_get)

    r = v.safe_get("https://commisrestaurant.com/",
                   allow_broken_chain_for="commisrestaurant.com")
    assert r is not None
    assert False in calls, "the named host was never retried unverified"


def test_redirect_target_never_inherits_the_tls_exception(monkeypatch):
    import src.venue_images as v
    monkeypatch.setattr(v, "_url_is_public", lambda u: True)

    class Redirect:
        status_code = 302
        headers = {"location": "https://cdn.example.net/x.jpg"}
        url = "https://commisrestaurant.com/"
        text = ""
    calls = []
    def fake_get(url, **kw):
        calls.append((url, kw.get("verify", True)))
        if url.startswith("https://commisrestaurant.com"):
            return Redirect()
        raise RuntimeError("CERTIFICATE_VERIFY_FAILED")
    monkeypatch.setattr("requests.get", fake_get)
    assert v.safe_get("https://commisrestaurant.com/",
                      allow_broken_chain_for="commisrestaurant.com") is None
    # the CDN hop must have been attempted WITH verification
    cdn = [c for c in calls if "cdn.example.net" in c[0]]
    assert cdn and all(verify is not False for _, verify in cdn)


def test_html_entities_are_decoded_before_name_matching():
    """`Sons &amp; Daughters` normalized to `sonsampdaughters`, so the venue's
    real page failed verification and was cached as absent."""
    from src.venue_images import _page_names_venue
    assert _page_names_venue("<h1>Sons &amp; Daughters</h1>", "Sons & Daughters")


def test_og_image_decodes_entities_in_query_strings():
    from src.venue_images import _og_image
    html = '<meta property="og:image" content="https://x.com/p.jpg?w=1&amp;h=2">'
    assert _og_image(html) == "https://x.com/p.jpg?w=1&h=2"


def test_short_name_page_check_needs_a_whole_token():
    """`Coi` matched inside `Coin-Op`, handing the venue a stranger's page."""
    from src.venue_images import _page_names_venue
    assert not _page_names_venue("<h1>Coin-Op</h1>", "Coi")
    assert _page_names_venue("<h1>Coi</h1>", "Coi")


def test_tier_counts_only_after_the_image_downloads(monkeypatch):
    """A declared image that 403s must not skip the later tiers.

    The website tier returned success on finding an og:image URL, so social and
    Mapbox were never tried; the final download then cleared `url`, leaving no
    photo even though another tier could have supplied one.
    """
    import src.venue_images as v

    monkeypatch.setattr(v, "find_official_site", lambda venue, attempts=3:
                        ("https://venue.example/", "found"))
    monkeypatch.setattr(v, "find_booking_links", lambda venue: {})
    monkeypatch.setattr(v, "tier_website", lambda *a, **k:
                        {"url": "https://venue.example/broken.jpg",
                         "source": "venue-website", "site": "https://venue.example/"})
    monkeypatch.setattr(v, "tier_social", lambda *a, **k:
                        {"url": "https://cdn.example/good.jpg", "source": "venue-social"})

    def fake_download(url, key, **kw):
        return "venue-images/x.jpg" if url.endswith("good.jpg") else None
    monkeypatch.setattr(v, "download_image", fake_download)

    rec, status = v.resolve_venue("Test Venue", use_serp=True)
    assert status == "found"
    assert rec["url"] == "venue-images/x.jpg", "fallback tier was never reached"
    assert rec["source"] == "venue-social"


def test_booking_discovery_runs_without_a_website(monkeypatch):
    """A venue whose only web presence is its booking page has no official site
    by definition, and its booking link was never searched for."""
    import src.venue_images as v

    monkeypatch.setattr(v, "find_official_site", lambda venue, attempts=3: (None, "absent"))
    called = []
    monkeypatch.setattr(v, "find_booking_links",
                        lambda venue: called.append(venue) or {"resy": "https://resy.com/x"})
    monkeypatch.setattr(v, "tier_website", lambda *a, **k: None)
    monkeypatch.setattr(v, "tier_social", lambda *a, **k: None)

    rec, status = v.resolve_venue("Booking Only", use_serp=True)
    assert called == ["Booking Only"]
    assert status == "found"
    assert rec["booking"] == {"resy": "https://resy.com/x"}


def test_social_tier_fetches_the_platform_it_saw(monkeypatch):
    """A facebook.com link was opened as instagram.com/<handle>, which confirms
    nothing — and the photo was accepted with no name check."""
    import src.venue_images as v

    fetched = []

    class R:
        status_code = 200
        text = ('<a href="https://www.facebook.com/somebistro">fb</a>'
                '<h1>Some Bistro</h1>'
                '<meta property="og:image" content="https://cdn.example/p.jpg">')
        url = "https://www.facebook.com/somebistro/"
    monkeypatch.setattr(v, "safe_get", lambda u, **k: fetched.append(u) or R())
    rec = v.tier_social("Some Bistro", "https://somebistro.example/")
    assert any("facebook.com" in u for u in fetched)
    assert not any("instagram.com" in u for u in fetched), "wrong platform fetched"
    assert rec and rec["site"] == "facebook.com"


def test_social_photo_is_rejected_when_the_profile_does_not_name_the_venue(monkeypatch):
    import src.venue_images as v

    class R:
        status_code = 200
        text = '<h1>Someone Else Entirely</h1><meta property="og:image" content="https://cdn.example/p.jpg">'
        url = "https://www.instagram.com/handle/"
    monkeypatch.setattr(v, "safe_get", lambda u, **k: R())
    assert v.tier_social("Some Bistro", "https://somebistro.example/") is None


def test_venue_read_tries_both_index_shapes():
    """to_venue/from_venue are plain keyword fields on an index ensure_index
    created, but text-with-subfield on the legacy live index. Reading only one
    shape returns zero venues on the other. Asserted behaviourally through the
    real function, not by grepping main()'s source."""
    from src.venue_images import _distinct_field
    asked = []

    def only_subfield(_es, name):
        asked.append(name)
        if name.endswith(".keyword"):
            return {"Zuni Cafe"}
        raise RuntimeError("Fielddata is disabled")   # bare field unusable
    assert _distinct_field("to_venue", only_subfield, None) == {"Zuni Cafe"}
    assert asked == ["to_venue", "to_venue.keyword"], "did not try both shapes"

    def only_bare(_es, name):
        if name.endswith(".keyword"):
            raise RuntimeError("unknown field [keyword]")
        return {"Benu"}
    assert _distinct_field("to_venue", only_bare, None) == {"Benu"}


def test_a_changed_verdict_reopens_a_cached_venue():
    """A cached answer used to win unconditionally, so a corrected website
    verdict never reached the resolution loop."""
    import inspect
    import src.venue_images as v
    src = inspect.getsource(v.main)
    assert "superseded(" in src, "no cache invalidation on verdict change"
    assert 'entry.get("site")' in src, "verdict is not compared to the cache"


# ── round 9 findings ────────────────────────────────────────────────────────

def test_booking_slug_matches_short_words_in_sequence():
    """`Per Se` has no 4-letter token and its name is not one slug fragment, so
    both old checks failed and valid links were dropped."""
    from src.venue_images import _slug_names_venue as f
    assert f("/r/per-se", "Per Se")
    assert f("/r/rich-table-san-francisco", "Rich Table")
    assert f("/r/state-bird-provisions", "State Bird Provisions")


def test_booking_slug_still_rejects_a_different_restaurant():
    """The boundary check must survive the sequence match."""
    from src.venue_images import _slug_names_venue as f
    assert not f("/r/coin-op-san-francisco", "Coi")
    assert not f("/r/coin-op", "Coi")
    assert not f("/r/state-bird-annex", "State Bird Provisions")


def test_booking_slug_handles_connectives_and_possessives():
    from src.venue_images import _slug_names_venue as f
    assert f("/r/sons-and-daughters", "Sons & Daughters")
    assert f("/r/mister-jius", "Mister Jiu's")
    assert f("/zunicafe", "Zuni Cafe")
    assert f("/r/coirestaurant", "Coi")


def test_booking_link_search_pages_still_rejected(monkeypatch):
    """Search/editorial pages must not come back when the matcher changed."""
    import src.search as bd
    import src.venue_images as v
    bad = ["https://resy.com/city/san-francisco?query=Per%20Se",
           "https://www.opentable.com/s?term=per%20se",
           "https://blog.resy.com/2024/04/per-se"]
    monkeypatch.setattr(bd, "search", lambda q, num=10: [{"url": u, "title": ""} for u in bad])
    assert v.find_booking_links("Per Se") == {}


def test_field_shape_errors_are_recoverable():
    from src.venue_images import _is_field_shape_error
    assert _is_field_shape_error(RuntimeError("Fielddata is disabled on [to_venue]"))
    assert _is_field_shape_error(RuntimeError("unknown field [keyword]"))


def test_infrastructure_errors_are_not_swallowed():
    """A dead cluster used to look like "0 venues, exit 0"."""
    from src.venue_images import _is_field_shape_error
    assert not _is_field_shape_error(RuntimeError("Connection refused"))
    assert not _is_field_shape_error(RuntimeError("401 Unauthorized"))
    assert not _is_field_shape_error(RuntimeError("no such index [bone-fides-edges]"))
    assert not _is_field_shape_error(TimeoutError("timed out"))


def test_main_uses_the_real_distinct_helper():
    """main() must read venues through distinct_venues(), not a copy that could
    drift from the tested implementation."""
    import inspect
    import src.venue_images as v
    src = inspect.getsource(v.main)
    assert "distinct_venues(es" in src, "main does not use the tested helper"
    body = inspect.getsource(v.distinct_venues)
    assert "_distinct_field" in body


# ── round 10 findings ───────────────────────────────────────────────────────

def test_joined_names_keep_their_booking_links():
    """"The Progress" -> /theprogress dropped out: connectives were stripped
    from the venue side but the joined path keeps them."""
    from src.venue_images import _slug_names_venue as f
    assert f("/theprogress", "The Progress")
    assert f("/houseofprimerib", "House of Prime Rib")
    assert f("/sonsanddaughterssf", "Sons & Daughters")


def test_joined_name_match_still_respects_a_boundary():
    from src.venue_images import _slug_names_venue as f
    assert not f("/r/coin-op-san-francisco", "Coi")
    assert not f("/r/state-bird-annex", "State Bird Provisions")
    assert not f("/r/benumbing", "Benu")


def test_a_partial_read_is_not_a_failed_read(monkeypatch):
    """An empty from_venue legitimately returns an empty set; raising the
    earlier shape error then aborted the run before to_venue was read.

    Drives the REAL _distinct_field: the previous version defined its own copy,
    so reverting the production fix left this test green.
    """
    from src.venue_images import _distinct_field

    def fake_read(_es, name):
        if name == "from_venue":
            raise RuntimeError("Fielddata is disabled on [from_venue]")
        if name == "from_venue.keyword":
            return set()                 # completes, but empty
        return {"A", "B"}

    assert _distinct_field("from_venue", fake_read, None) == set()   # no raise
    assert _distinct_field("to_venue", fake_read, None) == {"A", "B"}


def test_distinct_venues_reads_both_fields_through_the_real_function(monkeypatch):
    """The end-to-end path main() uses: an empty `from_venue` must not stop
    `to_venue` from being read."""
    from src.venue_images import distinct_venues

    def fake_read(_es, name):
        if name == "from_venue":
            raise RuntimeError("Fielddata is disabled on [from_venue]")
        if name == "from_venue.keyword":
            return set()
        if name == "to_venue.keyword":
            return {"Zuni Cafe"}
        raise RuntimeError("Fielddata is disabled on [to_venue]")
    assert distinct_venues(None, fake_read) == {"Zuni Cafe"}


def test_distinct_raises_when_no_shape_can_be_read():
    """Reverting `answered` would make this raise on the empty read instead."""
    import pytest
    from src.venue_images import _distinct_field

    def always_shape_error(_es, _name):
        raise RuntimeError("Fielddata is disabled")

    with pytest.raises(RuntimeError):
        _distinct_field("from_venue", always_shape_error, None)


def test_distinct_propagates_a_non_shape_failure():
    """A dead cluster must stop the run, not read as "0 venues"."""
    import pytest
    from src.venue_images import _distinct_field

    def connection_refused(_es, _name):
        raise RuntimeError("Connection refused")

    with pytest.raises(RuntimeError, match="Connection refused"):
        _distinct_field("from_venue", connection_refused, None)


# ── identity: a name match is not a venue match ─────────────────────────────

def test_domain_shape_decides_identity():
    """Recovered results included a beauty salon, a fintech and a
    Minnesota bar that all contain the venue's name."""
    from src.venue_images import _domain_names_venue as f
    # rejected: name + a different KIND of business, or a company TLD
    assert not f("https://plumorganicbeauty.com/", "Plum")
    assert not f("https://haven.inc/", "Haven")
    assert not f("https://www.antidotelegal.com/", "Antidote")
    assert not f("https://www.astastrings.org/", "Asta")
    assert not f("https://alembicrarebooks.com/", "Alembic")
    assert not f("https://theminagroup.com/", "Michael Mina")


def test_domain_shape_accepts_the_venue_own_sites():
    from src.venue_images import _domain_names_venue as f
    # name + venue descriptor: unambiguous
    assert f("https://coirestaurant.com/", "Coi")
    assert f("https://bixrestaurant.com/", "Bix")
    assert f("https://www.azizasf.com/", "Aziza")
    assert f("https://www.delfinasf.com/", "Delfina")
    assert f("https://www.sonsanddaughterssf.com/", "Sons & Daughters")


def test_a_bare_name_domain_is_not_proof_of_identity():
    """Any business anywhere owns its own name on a generic TLD. parktavern.net
    is a bowling alley in Minnesota; betelnut.co is 39 characters of nothing.
    A bare name has to be corroborated by the page."""
    from src.venue_images import _domain_verdict, _domain_names_venue
    assert _domain_verdict("https://parktavern.net/", "Park Tavern") is None
    assert _domain_verdict("https://www.betelnut.co/", "Betelnut") is None
    assert not _domain_names_venue("https://parktavern.net/", "Park Tavern")
    # a company TLD on a bare name is a definite NO
    assert _domain_verdict("https://haven.inc/", "Haven") is False


def test_a_local_namesake_is_still_rejected():
    """Plum Organic Beauty is IN San Francisco, so a locality check alone
    would hand it the restaurant's dossier."""
    from src.venue_images import _page_names_venue
    page = "<h1>Plum Organic Beauty</h1><p>holistic beauty in San Francisco</p>"
    assert not _page_names_venue(page, "Plum", url="https://plumorganicbeauty.com/")


def test_locality_still_admits_a_domain_that_is_not_name_shaped():
    """A domain whose shape settles nothing falls back to the page's own
    locality. Name + "group" IS a recognised descriptor, so it would settle it;
    a descriptive phrase the word lists don't know does not."""
    from src.venue_images import _page_names_venue, _domain_verdict
    assert _domain_verdict("https://www.somebistrogroup.com/", "Some Bistro") is True
    # "hospitalitygroupcollective" is not in the descriptor vocabulary, so the
    # domain is inconclusive and the page has to carry identity.
    page = "<h1>Some Bistro</h1><p>Open nightly in San Francisco</p>"
    assert _page_names_venue(page, "Some Bistro",
                             url="https://www.somebistrohospitalitygroupcollective.com/")
    # the same page without a locality signal is not enough
    assert not _page_names_venue("<h1>Some Bistro</h1>", "Some Bistro",
                                 url="https://www.somebistrohospitalitygroupcollective.com/")


def test_limit_zero_resolves_nothing():
    """`if limit:` treated 0 as "no limit" and started the full 4,754-venue
    run, downloading images for a corpus when the caller asked for none."""
    import inspect
    import src.venue_images as v
    src = inspect.getsource(v.main)
    assert "if limit is not None:" in src
    assert "max(0, int(" in src


# ── round 11 findings (Greptile on PR #14) ──────────────────────────────────

def test_decade_phrases_do_not_become_exact_years():
    """"the 1970s" names a span. Stamping year=1970 displays and sorts an
    exact year the citation never supported."""
    from src.eras import _year, era_bucket
    assert _year("1970s") is None
    assert _year("mid-1980s") is None
    assert _year("1990s") is None
    # the decade stamp survives, which is the honest grain
    assert era_bucket("1970s") == "pre-1990"
    assert era_bucket("1990s") == "1990s"
    # a real year is still a year
    assert _year("October 2014") == 2014
    assert _year("fall 2017") == 2017


def test_completion_rows_carry_year():
    """fetch_person_edges requested year but dropped it, so a completion row
    merged beside a ranked row partitioned on a different time key and one move
    split into an e2010s row and a y2013 row."""
    import inspect
    import src.venue_images  # noqa: F401  (import path sanity)
    import importlib.util, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in ("src/dossier.py",):
        src = open(os.path.join(root, rel), encoding="utf-8").read()
        # the completion builder must copy year out of _source
        assert src.count('"year": s.get("year")') >= 2, (
            f"{rel}: year is missing from one of the two payload paths")


def test_resolve_errors_are_reported_not_swallowed():
    """A disk or code error could fail hundreds of venues while the run printed
    only progress and exited 0."""
    import inspect
    import src.venue_images as v
    src = inspect.getsource(v.main)
    assert "failed.append" in src, "per-venue errors are discarded"
    assert "venues raised while resolving" in src, "no failure report"
    assert "return 1" in src, "a failed run must not exit 0"


# ── round 12 findings (Greptile on PR #15) ─────────────────────────────────

def test_booking_links_must_be_in_this_metro():
    """Resy/OpenTable put the city in the path. "The Beehive" resolved to a
    Dallas restaurant and "Ubuntu" to a café in San Juan Capistrano."""
    from src.venue_images import _booking_city_mismatch
    assert _booking_city_mismatch("/cities/dallas-fort-worth-tx/venues/beehive-restaurant-lounge")
    assert _booking_city_mismatch("/cities/san-juan-capistrano-ca/venues/ubuntu-cafe")
    assert _booking_city_mismatch("/r/au-pied-de-cochon-paris")
    # the Bay Area and nearby wine country are in-corpus, not mismatches
    assert not _booking_city_mismatch("/cities/san-francisco-ca/venues/7-adams")
    assert not _booking_city_mismatch("/r/benu-san-francisco")
    assert not _booking_city_mismatch("/r/the-progress-san-francisco-1")


def test_a_generic_single_word_does_not_identify_a_restaurant():
    """"The Bird" matched state-bird-provisions and social-bird, which are
    different restaurants."""
    from src.venue_images import _slug_names_venue as f
    assert not f("/r/state-bird-provisions-san-francisco", "The Bird")
    assert not f("/cities/san-francisco-ca/venues/social-bird", "The Bird")
    # a short DISTINCTIVE name is still fine
    assert f("/r/coi-san-francisco", "Coi")
    assert f("/r/coirestaurant", "Coi")
    assert f("/r/a16", "A16")


def test_plugin_and_tracker_assets_are_not_venue_photos():
    """RevSlider's bundled dummy.png and a metricool tracker pixel were both
    stored as high-confidence venue photographs."""
    from src.venue_images import _og_image
    for html in (
        '<meta property="og:image" content="https://x.com/wp-content/plugins/revslider/public/assets/assets/dummy.png">',
        '<meta property="og:image" content="https://tracker.metricool.com/c3po.jpg">',
        '<meta property="og:image" content="https://x.com/assets/assets/placeholder.jpg">',
    ):
        assert _og_image(html) is None, html


# ── booking links must be venue pages, not maps or lists ───────────────────

def test_proximity_and_landmark_pages_are_not_bookings(monkeypatch):
    """OpenTable emits /landmark/restaurants-near-<place> constantly — 79
    reached the cache. They list what is NEAR a place; a diner cannot book."""
    import src.search as bd
    import src.venue_images as v
    monkeypatch.setattr(bd, "search", lambda q, num=10: [
        {"url": "https://www.opentable.com/landmark/restaurants-near-benu", "title": ""},
        {"url": "https://www.opentable.com/nearby/restaurants-near-me-benu", "title": ""},
    ])
    assert v.find_booking_links("Benu") == {}


def test_opentable_directory_and_editorial_pages_are_not_bookings(monkeypatch):
    """Also directory shapes, also name-matched: /food-near-me/campbell passed
    for venue "Campbell", /metro/... for "San Francisco", and the editorial
    /features/ pages for whoever they list."""
    import src.search as bd
    import src.venue_images as v
    cases = [
        ("Campbell", "https://www.opentable.com/food-near-me/campbell"),
        ("San Francisco", "https://www.opentable.com/metro/san-francisco-restaurants"),
        ("Waterfront", "https://www.opentable.com/features/best-waterfront-restaurants-sf"),
        ("Mother", "https://www.opentable.com/events/mothers-day/metro/san-francisco"),
    ]
    for venue, url in cases:
        monkeypatch.setattr(bd, "search", lambda q, num=10, u=url: [{"url": u, "title": ""}])
        assert v.find_booking_links(venue) == {}, f"{url} accepted for {venue}"


def test_a_resy_city_list_is_rejected_for_a_venue_named_in_it(monkeypatch):
    """The earlier version searched "Benu" for a URL containing only
    `arcadia`, so _slug_names_venue rejected it on NAME and the test passed
    even with the Resy list filter removed. Ask for the venue the URL actually
    names, so only the list check can reject it."""
    import src.search as bd
    import src.venue_images as v
    monkeypatch.setattr(bd, "search", lambda q, num=10: [
        {"url": "https://resy.com/cities/arcadia-ca/list/book-tonight", "title": ""}])
    assert v.find_booking_links("Arcadia") == {}


def test_a_resy_city_venue_page_is_still_a_booking(monkeypatch):
    """The normal Resy shape has the city in the path. Rejecting every
    /cities/ URL would drop 150 real links."""
    import src.search as bd
    import src.venue_images as v
    monkeypatch.setattr(bd, "search", lambda q, num=10: [
        {"url": "https://resy.com/cities/san-francisco-ca/venues/7-adams", "title": ""}])
    assert v.find_booking_links("7 Adams").get("resy") == \
        "https://resy.com/cities/san-francisco-ca/venues/7-adams"


def test_all_three_platforms_are_searched():
    import inspect
    import src.venue_images as v
    src = inspect.getsource(v.find_booking_links)
    for p in ('"resy"', '"opentable"', '"tock"'):
        assert p in src, f"{p} is not searched"


# ── a venue's own site can settle that it closed ───────────────────────────

def test_a_closure_announcement_is_detected():
    from src.venue_images import _announces_closure
    assert _announces_closure("<p>Range Restaurant San Francisco is Now Closed</p>")
    assert _announces_closure("<p>Trick Dog has closed. Thank you for the years.</p>")
    assert _announces_closure("<p>We are closed. Thank you for 20 years.</p>")
    # A bare farewell with no closure object is NOT a closure. This assertion
    # used to accept "...we announce..." alone, which is precisely the bug that
    # closed open restaurants announcing a death or a departure. The phrase
    # needs to name what it is announcing.
    assert not _announces_closure("<p>It is with great sadness that we announce...</p>")
    assert _announces_closure(
        "<p>It is with great sadness that we announce we have closed.</p>")


def test_a_weekly_schedule_is_not_a_closure():
    """Farallon's own page says "We are closed on Sundays and Mondays" — a
    working restaurant. Reading that as closure marks it shut."""
    from src.venue_images import _announces_closure
    assert not _announces_closure("<p>We are closed on Sundays and Mondays.</p>")
    assert not _announces_closure("<p>We are closed for special events.</p>")
    assert not _announces_closure("<p>Closed on Thanksgiving Day.</p>")
    assert not _announces_closure("<p>Sundays: CLOSED</p>")
    assert not _announces_closure("<p>We are open Tuesday to Sunday.</p>")


# ── one restaurant written two ways is one identity ───────────────────────

def test_formatting_variants_fold_to_one_venue():
    """The corpus held 1,114 raw names for 442 venues: "Jardinière" (13 edges)
    and "Jardiniere" (15) were separate nodes, so every per-venue count was
    wrong and a dossier split in two."""
    from src.venue_images import canonical_venue as c
    for a, b in [("Jardinière", "Jardiniere"), ("Tosca Café", "Tosca Cafe"),
                 ("AL's Deli", "AL’s Deli"), ("À Côté", "A Cote"),
                 ("Baumé", "Baume"), ("COI", "Coi"),
                 # parenthetical is formatting when the words are identical
                 ("Ritz Carlton (San Francisco)", "Ritz-Carlton San Francisco"),
                 ("Bouchon (Beverly Hills)", "Bouchon Beverly Hills")]:
        assert c(a) == c(b), f"{a!r} and {b!r} should be one venue"


def test_different_locations_stay_separate():
    """Merging these would put one restaurant's moves on another's dossier."""
    from src.venue_images import canonical_venue as c
    for a, b in [("Stars (San Francisco)", "Stars (Seattle)"),
                 ("A16", "A16 (Oakland location)"),
                 ("4505 Burgers & BBQ (Divisadero location)",
                  "4505 Burgers & BBQ (Oakland location)"),
                 # a rename is not a formatting difference
                 ("Alfred's", "Alfred's Steakhouse")]:
        assert c(a) != c(b), f"{a!r} and {b!r} must stay apart"


def test_build_edge_doc_stamps_canonical_venue_keys():
    from src.es import build_edge_doc
    from src.venue_images import canonical_venue
    d = build_edge_doc({"person": "X", "source_url": "u",
                        "from_venue": "Jardinière", "to_venue": "Tosca Café"})
    assert d["from_venue_key"] == canonical_venue("Jardinière") == "jardiniere"
    assert d["to_venue_key"] == canonical_venue("Tosca Café") == "toscacafe"
    assert d["from_venue"] == "Jardinière"       # display form preserved


def test_a_leading_the_is_folded_for_identity():
    """"The French Laundry" and "French Laundry" are one restaurant — 65 and
    46 edges were being counted as two venues."""
    from src.venue_images import venue_identity as v
    assert v("The French Laundry") == v("French Laundry")
    assert v("The Slanted Door") == v("Slanted Door")
    assert v("the Commissary") == v("Commissary")
    assert v("The Fifth Floor") == v("Fifth Floor")


def test_only_the_is_stripped_never_a_or_an():
    """An earlier draft folded every article, which destroyed real names:
    Alamar became "La Mar" and "AQ Restaurant & Bar" became "Q Restaurant &
    Bar" — different restaurants in both cases."""
    from src.venue_images import venue_identity as v
    assert v("Alamar") != v("La Mar")
    assert v("AQ Restaurant & Bar") != v("Q Restaurant & Bar")
    # and identity still respects location, as canonical_venue does
    assert v("Stars (San Francisco)") != v("Stars (Seattle)")


# ── the owner's adjudication of name groups (ui/venue_aliases.json) ────────

def test_aliases_collapse_the_spellings_a_human_ruled_on():
    from src.venue_aliases import identity
    pairs = [
        ("Fifth Floor Restaurant", "Fifth Floor"),
        ("Michael Mina restaurant", "Michael Mina"),
        ("Restaurant Michael Mina (original)", "Michael Mina"),
        ("Alfred's", "Alfred's Steakhouse"),
        ("Scoma’s", "Scoma's restaurant"),
        ("DOSA", "Dosa"),
        ("Babu Ji (San Francisco)", "Babu Ji"),
        ("A16 Oakland", "A16 (Oakland location)"),
    ]
    for a, b in pairs:
        assert identity(a) == identity(b), f"{a!r} and {b!r} should share an identity"


def test_location_specific_brands_keep_their_cities_apart():
    """"Stars (Seattle)" and "Stars (San Francisco)" are different businesses
    by the owner's ruling — merging would put Seattle moves on the SF dossier."""
    from src.venue_aliases import identity, is_location_variant
    assert is_location_variant("Stars (Seattle)")
    assert is_location_variant("Stars (San Francisco)")
    assert identity("Stars (Seattle)") != identity("Stars (San Francisco)")
    # but the two spellings of the SAME city still agree
    assert identity("Stars (San Francisco)") == identity("Stars San Francisco")
    # Mission Chinese Food and Tartine Manufactory likewise
    assert identity("Mission Chinese Food (New York)") != \
           identity("Mission Chinese Food")
    assert identity("Tartine Manufactory (Los Angeles)") != \
           identity("Tartine Manufactory (San Francisco)")


def test_aliases_never_apply_without_a_recorded_ruling():
    """The file is authoritative: an unrecorded venue keeps its own name."""
    from src.venue_aliases import identity
    assert identity("Something Nobody Ruled On") == \
           identity("Something Nobody Ruled On")
    assert identity("Something Nobody Ruled On") != identity("Fifth Floor")


def test_alias_file_is_well_formed():
    import json, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = json.load(open(os.path.join(root, "ui", "venue_aliases.json")))
    assert d["merge"], "no merge rulings"
    # a canonical title must not also appear as a location-specific variant
    loc_all = {v for vs in (d.get("locations") or {}).values() for v in vs}
    overlap = set(d["merge"]) & loc_all
    assert not overlap, f"contradictory rulings: {sorted(overlap)}"


# ── the identity rule exists twice; the copies must not drift ───────────────

def test_base_identity_matches_the_module_rule():
    """venue_aliases.base_identity is a deliberate copy of venue_identity.

    It has to be a copy: venue_aliases ships into the Vercel function bundle,
    which contains no src/ package, so an import there would 500 the stats
    endpoint. A copy can drift, so this pins the two together on the cases that
    the rule is actually FOR — the leading article and the names that must NOT
    lose their first three letters.
    """
    from src.venue_aliases import base_identity
    from src.venue_images import venue_identity

    cases = [
        "The French Laundry", "French Laundry", "The Slanted Door",
        "Slanted Door", "Fifth Floor", "Restaurant Michael Mina",
        "Stars (Seattle)", "Stars San Francisco", "Jardinière", "A16",
        "the Mandarin", "Ritz Carlton (SF)",
        # the regression this exists to catch: "the" is a PREFIX of these
        "Theodore", "Theater Cafe", "Thea", "Theo",
    ]
    for c in cases:
        assert base_identity(c) == venue_identity(c), (
            f"{c!r}: the bundled identity copy drifted from venue_images")


def test_article_fold_needs_a_whole_word():
    """A leading-article rule that runs on the squashed key eats first letters.

    "Theodore".startswith("the") was true, so it became "odore" — a different
    restaurant. The article is only folded when it is a whole word.
    """
    from src.venue_images import venue_identity

    assert venue_identity("The French Laundry") == venue_identity("French Laundry")
    assert venue_identity("Theodore") == "theodore"
    assert venue_identity("Theater Cafe") == "theatercafe"
    assert venue_identity("Thea") == "thea"
    # and a bare "The" is not a venue to strip down to nothing
    assert venue_identity("The") != ""


# ── a closed venue is a verdict even when it has no photo ───────────────────

def test_closure_survives_without_an_image(monkeypatch):
    """own() used to drop a record whose url was empty. A closure has none.

    tier_website() settles that the venue is shut, then own() discarded the
    record for having no url and the run cached "absent" — a venue that will be
    probed forever.
    """
    import src.venue_images as v

    monkeypatch.setattr(v, "find_official_site",
                        lambda *a, **k: ("https://shut.example/", "found"))
    monkeypatch.setattr(v, "find_booking_links", lambda *a, **k: {})
    monkeypatch.setattr(v, "tier_website", lambda *a, **k: {
        "url": None, "source": None, "site": "https://shut.example/",
        "confidence": "high", "closed": True,
        "evidence": "the venue's own site announces closure"})
    monkeypatch.setattr(v, "tier_social", lambda *a, **k: None)

    rec, status = v.resolve_venue("Shut Place")
    assert status == "closed", "a closure is a status, not a missing photo"
    assert rec["status"] == "closed"
    assert rec["url"] is None


def test_closed_venue_with_a_downloadable_photo_keeps_both(monkeypatch):
    """A shut venue can still serve its last hero image. Download it — but
    never record a remote URL the cache does not actually hold."""
    import src.venue_images as v

    monkeypatch.setattr(v, "find_official_site",
                        lambda *a, **k: ("https://shut.example/", "found"))
    monkeypatch.setattr(v, "find_booking_links", lambda *a, **k: {})
    monkeypatch.setattr(v, "tier_website", lambda *a, **k: {
        "url": "https://shut.example/hero.jpg", "source": "venue-website",
        "site": "https://shut.example/", "confidence": "high", "closed": True})
    monkeypatch.setattr(v, "download_image", lambda *a, **k: "venue-images/shut.jpg")

    rec, status = v.resolve_venue("Shut Place")
    assert status == "closed"
    assert rec["url"] == "venue-images/shut.jpg", "must be the LOCAL path"
    assert rec["closed"] is True


def test_closed_venue_whose_photo_will_not_download_does_not_invent_one(monkeypatch):
    """The review finding: `own()` returned the closed record before fetching,
    so the cache claimed a photo while holding a hotlink."""
    import src.venue_images as v

    monkeypatch.setattr(v, "find_official_site",
                        lambda *a, **k: ("https://shut.example/", "found"))
    monkeypatch.setattr(v, "find_booking_links", lambda *a, **k: {})
    monkeypatch.setattr(v, "tier_website", lambda *a, **k: {
        "url": "https://shut.example/hero.jpg", "source": "venue-website",
        "site": "https://shut.example/", "confidence": "high", "closed": True})
    monkeypatch.setattr(v, "download_image", lambda *a, **k: None)

    rec, status = v.resolve_venue("Shut Place")
    assert status == "closed"
    assert rec["url"] is None, "no local photo, so no photo may be claimed"


def test_a_closure_does_not_spend_the_social_tier(monkeypatch):
    """The venue is shut; hunting it a photo is wasted work."""
    import src.venue_images as v

    calls = {"social": 0}
    monkeypatch.setattr(v, "find_official_site",
                        lambda *a, **k: ("https://shut.example/", "found"))
    monkeypatch.setattr(v, "find_booking_links", lambda *a, **k: {})
    monkeypatch.setattr(v, "tier_website", lambda *a, **k: {
        "url": None, "site": "https://shut.example/", "closed": True})
    monkeypatch.setattr(v, "tier_social",
                        lambda *a, **k: calls.__setitem__("social", calls["social"] + 1))

    v.resolve_venue("Shut Place")
    assert calls["social"] == 0


def test_matching_form_strips_the_article_too():
    """identity_words kept a leading "The"; identity did not.

    So "The Progress" and "Progress" were ONE venue for counting and TWO for
    dossier matching, and the whole-word comparison failed to join them — one
    career split across two cards. Both forms must apply the same rule.
    """
    from src.venue_aliases import identity, identity_words

    for bare, articled in (("Progress", "The Progress"),
                           ("Commissary", "The Commissary"),
                           ("French Laundry", "The French Laundry")):
        assert identity(bare) == identity(articled), (
            f"{bare}/{articled}: the counting identity does not collapse")
        assert identity_words(bare) == identity_words(articled), (
            f"{bare}/{articled}: the MATCHING identity does not collapse, so "
            f"one career splits across two dossier cards")


def test_article_fold_does_not_eat_real_word_starts():
    """The matching form strips "the" as a WORD, not a character prefix."""
    from src.venue_aliases import identity_words

    assert identity_words("Theodore") == "theodore"
    assert identity_words("Theater Cafe") == "theater cafe"
    assert identity_words("Thea") == "thea"
    # a bare "The" is not a venue to reduce to nothing
    assert identity_words("The") == "the"


def test_word_boundaries_survive_for_matching():
    """Matching must compare TOKENS: a character prefix joined El Faro to
    El Farolito, which are different restaurants."""
    from src.venue_aliases import identity_words

    assert identity_words("El Faro") == "el faro"
    assert identity_words("El Farolito") == "el farolito"
    assert not identity_words("El Farolito").startswith(
        identity_words("El Faro") + " ")


# ── the operator-vs-restaurant case (owner's ruling, 2026-11-16) ────────────

def test_plumpjack_operator_prefix_does_not_merge_two_restaurants():
    """PlumpJack is Balboa Cafe's OPERATOR, and also its own restaurant.

    The corpus writes "PlumpJack Balboa Cafe" for one business, so a naive
    prefix rule would be tempting — but it would also fold "PlumpJack Cafe"
    (a different restaurant) into Balboa Cafe, putting one kitchen's chefs on
    the other's dossier. The grouping is recorded as a ruling, not inferred.
    """
    from src.venue_aliases import identity

    # same restaurant, written with its operator in front
    balboa = {identity(n) for n in (
        "Balboa Cafe", "PlumpJack Balboa Cafe", "Balboa Café Mill Valley")}
    assert len(balboa) == 1, f"Balboa spellings split: {balboa}"

    # and a genuinely different restaurant that shares the operator
    cafe = {identity(n) for n in (
        "PlumpJack Cafe", "Plumpjack Cafe", "PlumpJack Cafe (San Francisco)",
        "PlumpJack", "PlumpJack restaurant")}
    assert len(cafe) == 1, f"PlumpJack Cafe spellings split: {cafe}"

    assert balboa != cafe, (
        "Balboa Cafe and PlumpJack Cafe are different restaurants; merging "
        "them attaches one kitchen's chefs to the other")

    # the other two properties stay their own
    assert identity("PlumpJack Squaw Valley") != identity("PlumpJack Cafe")
    assert identity("PlumpJack's Farm at the Carneros Inn") != identity("PlumpJack Cafe")


def test_plumpjack_empire_is_not_a_venue():
    """It is the group, not a restaurant. Counting it adds a kitchen that does
    not exist."""
    from src import dossier as ui

    assert ui._is_junk_venue("PlumpJack empire")
    # the actual restaurants must survive the same filter
    for name in ("PlumpJack Cafe", "Balboa Cafe", "PlumpJack Balboa Cafe"):
        assert not ui._is_junk_venue(name), f"{name} wrongly dropped"


def test_a_farewell_plus_a_weekly_schedule_is_still_open():
    """Reported three times because the single phrases passed and the
    COMBINATION did not.

    "Thank you for all the wonderful reviews" alone was already false. But a
    page carrying BOTH a thank-you and its opening hours was marked permanently
    shut, because the corroboration search matched the bare word "closed" inside
    "We are closed on Sundays" — a schedule. A working restaurant's own page
    would have been recorded as a closure.
    """
    import src.venue_images as v

    open_pages = [
        "Thank you for all the wonderful reviews. We are closed on Sundays.",
        "Thank you for the years! We are closed on Mondays and Tuesdays.",
        "Our kitchen has closed for the evening. Thank you for everything!",
        "Thank you for all the wonderful reviews! Closed on Thanksgiving.",
        "The dining room is now closed for the season.",
        "Thank you for a wonderful year. See you in spring!",
    ]
    for p in open_pages:
        assert not v._announces_closure(p), f"open restaurant marked shut: {p!r}"

    real_closures = [
        "It is with great sadness that we announce we have closed.",
        "The restaurant has permanently closed.",
        "Range Restaurant San Francisco is Now Closed",
        "Trick Dog has closed. Thank you for the years.",
        "We are closed. Thank you for 20 years.",
        "We have closed our doors.",
        "This location is now closed",
    ]
    for p in real_closures:
        assert v._announces_closure(p), f"real closure missed: {p!r}"


def test_a_farewell_phrase_alone_is_not_a_closure():
    """THE finding, finally reproduced.

    The bot said this five times with the same two example phrases, both of
    which I had already fixed. Testing those phrases was the mistake: the class
    of bug is that a farewell line was accepted ALONE. Open restaurants publish
    "it is with great sadness" about a founder's death, a chef leaving, or a
    cancelled service — and every one of those was marked permanently closed.

    A farewell phrase now needs a closure object in the same sentence, and that
    object must not be a schedule or a recurrence.
    """
    import src.venue_images as v

    open_pages = [
        "It is with great sadness that we announce the passing of our founder.",
        "It is with great sadness that we say goodbye to our pastry chef.",
        "We are sad to announce that our head chef is leaving.",
        "We regret to announce that tonight's service is cancelled.",
        "It is with a heavy heart that we close our doors each night at 10pm.",
        "We are sad to announce our summer menu has ended.",
    ]
    for p in open_pages:
        assert not v._announces_closure(p), f"open restaurant marked shut: {p!r}"

    closures = [
        "It is with great sadness that we announce we have closed.",
        "We are sad to announce that we are closing our doors after 20 years.",
        "It is with great sadness that we announce our final service.",
        "It is with a heavy heart that we announce the closure of the restaurant.",
    ]
    for p in closures:
        assert v._announces_closure(p), f"real closure missed: {p!r}"


def test_closure_detection_full_matrix():
    """Both directions, every phrase shape the corpus actually contains."""
    import src.venue_images as v

    open_pages = [
        "Thank you for all the wonderful reviews",
        "Our kitchen has closed for the evening",
        "Thank you for all the wonderful reviews. We are closed on Sundays.",
        "Our kitchen has closed for the evening. Thank you for everything!",
        "We are closed on Sundays and Mondays.",
        "The dining room is now closed for the season.",
        "Closed (private events only)",
        "Thank you for a wonderful year. See you in spring!",
    ]
    for p in open_pages:
        assert not v._announces_closure(p), f"open restaurant marked shut: {p!r}"

    closures = [
        "We have closed our doors.",
        "The restaurant has permanently closed.",
        "Range Restaurant San Francisco is Now Closed",
        "Trick Dog has closed. Thank you for the years.",
        "We are closed. Thank you for 20 years.",
        "This location is now closed",
        "We will not be reopening.",
    ]
    for p in closures:
        assert v._announces_closure(p), f"real closure missed: {p!r}"


def test_a_dated_permanent_closure_is_still_a_closure():
    """The regression my previous fix introduced.

    To stop "it is with great sadness" firing on a chef's departure, I rejected
    any farewell whose next 90 characters mentioned "today"/"tomorrow"/"this
    week". That also swallowed real closures, because a permanent closure is
    routinely DATED:

      "our final service took place today"
      "we announce our closure today"

    A time word is evidence against a closure only for a GENERIC closure word
    ("tonight's service is cancelled"). An explicit closure noun — final
    service, last day, closure, closing our doors — decides on its own.
    """
    import src.venue_images as v

    dated_closures = [
        "It is with great sadness that we announce our final service took place today",
        "It is with great sadness that we announce our final service was yesterday",
        "We are sad to announce our last day of service was this week",
        "It is with great sadness that we announce our closure today",
    ]
    for p in dated_closures:
        assert v._announces_closure(p), f"dated closure missed: {p!r}"

    routine = [
        "We regret to announce that tonight's service is cancelled",
        "It is with a heavy heart that we close our doors each night at 10pm.",
        "We are sad to announce our summer menu has ended.",
    ]
    for p in routine:
        assert not v._announces_closure(p), f"routine notice marked shut: {p!r}"


def test_a_temporary_closure_is_not_a_permanent_one():
    """The P1 that blocked the merge.

    _EXPLICIT_CLOSURE accepted the word "closure" on sight, ahead of every
    temporary check. A verified restaurant page saying

      "We regret to announce our temporary closure for renovations until next
       week"

    was written to the cache as status="closed" — and a cached closure is never
    re-probed, so the venue stayed shut in the corpus permanently. The word
    "closure" was doing the work that "permanent" should be doing.

    The qualifier is scoped to the SENTENCE, so a leading "temporary" and a
    trailing "temporarily" both count, while a separate sentence about temporary
    staffing cannot veto a genuine closure notice.
    """
    import src.venue_images as v

    temporary = [
        "We regret to announce our temporary closure for renovations until next week",
        "It is with great sadness that we announce our temporary closure for "
        "renovations until next week",
        "We are sad to announce a temporary closure for renovation",
        "We have closed temporarily for renovations",
        "We have closed our doors temporarily",
        "The restaurant has shut down temporarily",
        "It is with great sadness that we announce our temporary closure until next week",
        "We regret to announce a brief closure",
    ]
    for p in temporary:
        assert not v._announces_closure(p), f"temporary closure marked permanent: {p!r}"

    # A dated notice is still a closure: the date is part of the announcement,
    # not a reason to doubt it. "for good" wins over a nearby "temporary".
    # The last case pins a bug in the first version of this fix, which used a
    # bare `in\w*` as a temporary marker — it matched the ordinary word "in"
    # and vetoed every closure dated by month or year.
    still_closed = [
        "It is with great sadness that we announce our final service took place today",
        "It is with great sadness that we announce our closure today",
        "Temporary staffing changes are coming. We have closed its doors for good.",
        "We have closed our doors in 2020.",
        "We have closed its doors in March after 40 years.",
    ]
    for p in still_closed:
        assert v._announces_closure(p), f"real closure missed: {p!r}"


def test_a_temporary_qualifier_must_attach_to_the_closure():
    """The P1 that blocked the merge after the previous fix.

    The first version of the temporary guard scanned the whole SENTENCE for
    "brief"/"temporary". That is the same class of mistake as matching a bare
    "closed": the word was treated as proof regardless of what it described.

      "After a brief farewell, we have closed our doors."

    is a permanent closure behind a short goodbye, and the sentence scan called
    it temporary — so the verified page lost its closure flag and was cached
    `found`, which is never re-probed.

    The qualifier now has to ATTACH: only function words may sit between it and
    the closure noun ("our temporary closure"), and an intervening noun means the
    qualifier belongs to something else.
    """
    import src.venue_images as v

    # "brief"/"temporary" describes something other than the closure.
    permanently_closed = [
        "After a brief farewell, we have closed our doors.",
        "After a brief farewell, the restaurant has closed its doors.",
        "After a short farewell message, we have closed our doors.",
        "Following a temporary farewell, the restaurant has closed its doors.",
    ]
    for p in permanently_closed:
        assert v._announces_closure(p), f"closure misread as temporary: {p!r}"

    # The qualifier does attach, so these stay open. Leading and trailing.
    temporary = [
        "We have closed our doors for a brief period.",
        "We are temporarily closed for renovations.",
        "We are briefly closed for maintenance.",
        "We will be briefly closed for inventory.",
    ]
    for p in temporary:
        assert not v._announces_closure(p), f"temporary closure marked permanent: {p!r}"


def test_every_shape_of_temporary_closure_stays_open():
    """This finding returned three times, so it gets a matrix rather than an
    example.

    The first two rounds fixed only the string the review quoted — the literal
    phrase it named passed, while the CLASS it described did not. Eleven of the
    twenty-six ways a venue announces a temporary shutdown still returned True,
    because the two paths that adjudicate a generic closure word ("closed",
    "service", "doors") had no temporary check at all. A venue that shuts for
    renovations and says so in any of these words was cached status="closed",
    and a cached closure is never re-probed.

    Every shape here names a closure AND says it is not permanent. All must stay
    open; the permanent matrix above guards the other direction.
    """
    import src.venue_images as v

    temporary = [
        # adjective attached to the closure noun
        "We regret to announce our temporary closure for renovations until next week",
        "We regret to announce a temporary closure for renovations",
        "We regret to announce our temporary closure",
        "It is with great sadness that we announce our temporary closure for renovations",
        "We regret to announce the temporary closure of our restaurant",
        "We regret to announce a brief closure",
        "We regret to announce our brief closure for renovations",
        "We regret to announce a short-term closure",
        "We regret to announce our seasonal closure",
        # adverb attached to the verb
        "We regret to announce that we will be closing temporarily",
        "We regret to announce we are closing temporarily for renovations",
        "We regret to announce we have closed temporarily",
        "We regret to announce the restaurant has closed temporarily",
        "We regret to announce that service is temporarily suspended",
        "It is with great sadness that we announce a temporary suspension of service",
        # a tail that postpones reopening
        "We regret to announce our closure until further notice",
        "We regret to announce our closure for the holidays",
        "We regret to announce we are closed until further notice",
        "We regret to announce we are closed for renovations",
        "We regret to announce our final service is postponed",
    ]
    for p in temporary:
        assert not v._announces_closure(p), f"temporary closure marked permanent: {p!r}"

    # The same shapes, made permanent by their own words, must still fire.
    still_closed = [
        "We regret to announce our closure for good",
        "We regret to announce we have closed our doors permanently",
        "It is with great sadness that we announce our final service took place today",
        "We are sad to announce our last day of service was this week",
        "We regret to announce our final service has concluded",
    ]
    for p in still_closed:
        assert v._announces_closure(p), f"real closure missed: {p!r}"


def test_no_temporary_notice_is_ever_permanent():
    """The exhaustive form of a finding that survived fourteen rounds.

    Every previous round fixed the sentence the review quoted and left the CLASS
    open, because "is this temporary?" was asked at some of the eight places the
    function says yes and forgotten at the rest. Catching that by reading is how
    it took fourteen rounds.

    So this does not test sentences. It crosses every preface with every
    temporary statement and every postponing tail — 1,470 notices, all of which
    name a closure AND say it is not permanent. Not one may be written to the
    cache as status="closed", because a cached closure is never re-probed.
    """
    import itertools

    import src.venue_images as v

    prefaces = [
        "",
        "We regret to announce ",
        "It is with great sadness that we announce ",
        "We are sad to announce ",
        "It is with a heavy heart that we announce ",
        "Thank you for everything. ",
        "Thank you for all the wonderful reviews. ",
    ]
    temporary_statements = [
        "our temporary closure", "a temporary closure",
        "the temporary closure of our restaurant", "our brief closure",
        "a brief closure", "our seasonal closure", "a short-term closure",
        "our temporary closing", "a temporary shutdown",
        "a temporary suspension of service", "we are temporarily closed",
        "we have closed temporarily", "we are closing temporarily",
        "the restaurant has closed temporarily",
        "service is temporarily suspended",
        "we are closed until further notice", "we are closed for renovations",
        "the restaurant has closed for renovations",
        "our closure until further notice", "our closure for the holidays",
        "our final service is postponed",
    ]
    postponing_tails = [
        "", " for renovations", " until next week", " until further notice",
        " for the holidays", " for repairs", " pending permits",
        " for maintenance", " for the season", " temporarily",
    ]

    leaked = []
    for preface, statement, tail in itertools.product(
            prefaces, temporary_statements, postponing_tails):
        notice = preface + statement + tail
        if v._announces_closure(notice):
            leaked.append(notice)
    assert not leaked, (
        "temporary notices cached as permanently closed:\n  "
        + "\n  ".join(repr(x) for x in leaked[:10]))


def test_explicit_permanence_is_not_erased_by_another_clause():
    """The regression from routing every verdict through the gate.

    "We are permanently closed, but our online shop remains temporarily
    available" states two different things: the restaurant is shut for good,
    the shop is briefly open. The gate's 60-character trailing window crossed
    the "but" and read `temporarily` as though it qualified the closure, so a
    venue whose own page says "permanently closed" was cached as `found`.

    Two fixes: the window now stops at a clause break, and phrases that state
    permanence in their own words ("permanently", "for good") are decisive
    rather than advisory.
    """
    import src.venue_images as v

    closed = [
        "We are permanently closed, but our online shop remains temporarily available",
        "We are permanently closed, though our gift cards are briefly available",
        "The restaurant has permanently closed, but our sister cafe is temporarily "
        "closed for renovations",
        "We have closed our doors for good, while our cookbook stays temporarily available",
    ]
    for p in closed:
        assert v._announces_closure(p), f"explicit permanence erased: {p!r}"


def test_closures_that_do_not_use_the_word_closed():
    """Requiring a clos/shut/door word dropped real closures.

    "_CLOSURE_WORD" exists to exclude NEUTRAL venue nouns ("restaurant",
    "business") that say nothing about closure — not to require one particular
    verb. "we are ceasing operations after 20 years" names a closure and has no
    clos/shut/door word, so narrowing the list too far lost it.
    """
    import src.venue_images as v

    closed = [
        "We regret to announce that we are ceasing operations after 20 years",
        "It is with great sadness that we announce we are ceasing operations",
        "We regret to announce the restaurant is halting service permanently",
        "We are sad to announce we are discontinuing service",
    ]
    for p in closed:
        assert v._announces_closure(p), f"closure without a clos/shut word missed: {p!r}"

    # ...while a neutral venue noun ALONE is still not a closure.
    not_closed = [
        "Our restaurant has a new menu",
        "The business is thriving",
        "It is with great sadness that we announce our head chef is leaving",
    ]
    for p in not_closed:
        assert not v._announces_closure(p), f"neutral mention marked closed: {p!r}"


def test_accented_and_plain_spellings_agree_on_official_sites():
    """Accents were treated as word separators, so an accented spelling
    produced NO matching words at all and lost a domain its plain twin won.

    `_preferred()` then picks one spelling before discovery runs, so "A Cote"
    kept acoterestaurant.com while "À Côté" recorded `absent` without ever
    fetching the candidate.
    """
    import src.venue_images as v

    assert v._is_official("https://acoterestaurant.com", "A Cote") is True
    assert v._is_official("https://acoterestaurant.com", "À Côté") is True
    # Folding must not admit lookalikes or join different venues.
    assert v._is_official("https://richtablesf.nevertrustadame.com", "Rich Table") is False
    assert v._is_official("https://elfarolito.com", "El Faro") is True  # short-name path


def test_service_line_verbs_must_name_the_venue_not_one_offering():
    """Two ways a service-line verb goes wrong, in opposite directions.

    Too LENIENT: "we are discontinuing our delivery service" ends one offering
    of a restaurant that is still trading, but `discontinuing` supplies the
    closure word and `service` supplies the object, so both checks passed.

    Too STRICT: the venue-wide check read a fixed 40-character window that
    crossed the full stop, so "Gift cards will be refunded" in the NEXT sentence
    became the thing being closed, and a genuinely shuttered venue lost its flag.
    """
    import src.venue_images as v

    closed = [
        "We regret to announce we are ceasing operations. Gift cards will be refunded.",
        "We regret to announce that we are ceasing operations after 20 years",
        "We are sad to announce we are discontinuing service",
        "We are sad to announce we are ceasing all service",
    ]
    for p in closed:
        assert v._announces_closure(p), f"venue-wide closure missed: {p!r}"

    still_open = [
        "We regret to announce that we are discontinuing our delivery service",
        "We regret to announce that we are discontinuing our delivery service. "
        "Gift cards will be refunded.",
        "We are discontinuing takeout service",
        "We are halting our catering service",
    ]
    for p in still_open:
        assert not v._announces_closure(p), f"service line marked as venue closure: {p!r}"


def test_delayed_reopening_is_not_a_permanent_closure():
    """"will not reopen" reads permanent but takes a delay."""
    import src.venue_images as v

    assert v._announces_closure("We will not reopen.")
    assert v._announces_closure("We will not be reopening.")
    assert not v._announces_closure("We will not reopen until spring")
    assert not v._announces_closure("We will not be reopening until next week")


def test_abbreviations_do_not_cut_a_closure_statement_short():
    """The clause check reads sentence boundaries, and a period inside a name
    is not one.

    "We regret to announce we are ceasing our St. Helena operations." lost
    `operations` when "St." was taken for a sentence end, so the venue-wide
    object vanished and a closed restaurant was cached `found`.

    The fix must not swing the other way either: "operations." ends a sentence,
    because a lone "s" is only an initial when it STANDS ALONE ("J. Kenji").
    """
    import src.venue_images as v

    closed = [
        "We regret to announce we are ceasing our St. Helena operations.",
        "We regret to announce we are ceasing operations at our St. Helena location.",
        "We regret to announce we are ceasing U.S. operations.",
        "We regret to announce we are ceasing operations. Gift cards will be refunded.",
    ]
    for p in closed:
        assert v._announces_closure(p), f"abbreviation hid a closure: {p!r}"

    # A real sentence break after the verb still separates a service line.
    still_open = [
        "We regret to announce that we are discontinuing our delivery service. "
        "Gift cards will be refunded.",
        "We are discontinuing our delivery service in St. Helena.",
    ]
    for p in still_open:
        assert not v._announces_closure(p), f"service line read as closure: {p!r}"


def test_which_object_comes_first_decides_the_closure():
    """Two attempts at a sentence boundary both failed, in opposite directions,
    so the boundary was removed rather than tuned again.

    A window with a period check could not tell a name from a statement end:
      "ceasing our St. Helena operations."   split at "St." and lost `operations`
      "ceasing operations in the U.S. Gift…" joined the next sentence

    The question does not need a boundary. It needs to know which object the
    verb takes FIRST: "ceasing operations" closes the venue even if gift cards
    are refunded afterwards; "discontinuing our delivery service" does not,
    because `delivery` is the object and `service` merely follows it.
    """
    import src.venue_images as v

    closed = [
        "We regret to announce we are ceasing our St. Helena operations.",
        "We regret to announce we are ceasing operations in the U.S. "
        "Gift cards will be refunded.",
        "We regret to announce we are ceasing operations. Gift cards will be refunded.",
        "We are sad to announce we are discontinuing service",
    ]
    for p in closed:
        assert v._announces_closure(p), f"venue closure missed: {p!r}"

    still_open = [
        "We regret to announce that we are discontinuing our delivery service",
        "We regret to announce that we are discontinuing our delivery service. "
        "Gift cards will be refunded.",
        "We are discontinuing takeout service",
        "We are halting our catering service",
    ]
    for p in still_open:
        assert not v._announces_closure(p), f"service line read as closure: {p!r}"


def test_the_subject_may_come_before_the_verb():
    """"all operations have ceased" closes a venue; "ceasing operations" does too.

    A forward-only window saw just "ceased." for the first shape and lost the
    venue, so the slice now covers both sides and the DECIDING object is still
    the one nearest the verb — which is what keeps "all operations have ceased.
    Gift cards will be refunded." venue-wide while "discontinuing our delivery
    service" stays a single offering.
    """
    import src.venue_images as v

    closed = [
        "We regret to announce all operations have ceased.",
        "We regret to announce all operations have ceased. Gift cards will be refunded.",
        "We regret to announce the restaurant has ceased trading.",
    ]
    for p in closed:
        assert v._announces_closure(p), f"subject-before-verb closure missed: {p!r}"

    still_open = [
        "Our delivery service has been discontinued.",
        "We are discontinuing takeout service",
    ]
    for p in still_open:
        assert not v._announces_closure(p), f"service line read as closure: {p!r}"


def test_a_service_line_must_be_the_verbs_object():
    """"the restaurant is discontinuing delivery service" is one offering ending.

    "the restaurant" is the grammatical SUBJECT, not the thing being stopped, so
    proximity alone read it as a venue closure. What separates the two is
    whether the service line directly follows the verb — its OBJECT — or sits in
    a later sentence.

      "discontinuing delivery service"        object  -> one offering ends
      "ceasing operations. Gift cards…"       later   -> venue closed
      "all operations have ceased."           subject -> venue closed
    """
    import src.venue_images as v

    still_open = [
        "We regret to announce the restaurant is discontinuing delivery service.",
        "We regret to announce the restaurant is discontinuing our delivery service.",
        "We are discontinuing takeout service",
        "Our delivery service has been discontinued.",
    ]
    for p in still_open:
        assert not v._announces_closure(p), f"service line read as closure: {p!r}"

    closed = [
        "We regret to announce all operations have ceased.",
        "We regret to announce all operations have ceased. Gift cards will be refunded.",
        "We regret to announce we are ceasing operations. Gift cards will be refunded.",
        "We are sad to announce we are discontinuing service",
    ]
    for p in closed:
        assert v._announces_closure(p), f"venue closure missed: {p!r}"


def test_a_refund_clause_does_not_undo_a_closure():
    """The finding: "…ceasing operations, but gift cards will be refunded."

    Only a full stop counted as separating the verb from a later service line,
    so the gap " operations, but " read as continuous and `gift cards` was taken
    for the verb's object — while `operations` was in fact the object and the
    refund was a separate statement. A clause conjunction separates too.

    Bare "while" also had to come out of the postponing-tail list: it vetoed
    "ceased operations while gift cards will be refunded", where it introduces
    an unrelated clause rather than a reason for closing.
    """
    import itertools

    import src.venue_images as v

    closed = [
        "We regret to announce we are ceasing operations, but gift cards will be refunded.",
        "We regret to announce we are ceasing operations and gift cards will be refunded.",
        "We regret to announce we are ceasing operations. Gift cards will be refunded.",
        "We regret to announce all operations have ceased, but gift cards will be refunded.",
        "We regret to announce all operations have ceased while gift cards will be refunded.",
    ]
    for p in closed:
        assert v._announces_closure(p), f"refund clause hid a closure: {p!r}"

    # The whole class, not just the quoted sentence: every closure statement
    # with a refund clause attached by every common conjunction.
    statements = [
        "we are ceasing operations", "all operations have ceased",
        "we are discontinuing service", "we have closed our doors",
        "the restaurant has closed permanently",
    ]
    conjunctions = ["but", "and", ", but", ", and", "while", "though",
                    "although", "however", "yet", "whereas", ", while", ", though"]
    followups = [
        "gift cards will be refunded", "gift cards remain available",
        "our online shop stays open", "delivery will continue",
        "catering is still available", "takeout remains available",
    ]
    missed = []
    for statement, conjunction, followup in itertools.product(
            statements, conjunctions, followups):
        notice = (f"We regret to announce {statement} "
                  f"{conjunction} {followup}.")
        notice = notice.replace(" , ", ", ")
        if not v._announces_closure(notice):
            missed.append(notice)
    assert not missed, (
        "closure lost behind a refund clause:\n  "
        + "\n  ".join(repr(x) for x in missed[:8]))


def test_a_service_line_remains_the_object_when_nothing_separates_it():
    """"the restaurant is discontinuing delivery service" is one offering.

    The venue noun before the verb is the grammatical SUBJECT — the thing doing
    the discontinuing — so it cannot be what the discontinuing closes. Only a
    venue object between the verb and the service line settles it, or a
    separator that makes the service line a new statement.
    """
    import src.venue_images as v

    still_open = [
        "We regret to announce the restaurant is discontinuing delivery service.",
        "We regret to announce the restaurant is discontinuing our delivery service.",
        "We are discontinuing our delivery service",
        "We are discontinuing takeout service",
        "We are halting our catering service",
        "Our delivery service has been discontinued.",
    ]
    for p in still_open:
        assert not v._announces_closure(p), f"service line read as closure: {p!r}"
