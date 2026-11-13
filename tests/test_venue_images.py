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
