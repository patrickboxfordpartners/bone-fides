"""SERP parsing: the discovery path must never silently return zero results.

The bug this file pins down: `serp()` requested `format: "raw"`, which the
Bright Data zone answers with Google's HTML shell, then read `data["organic"]`
from that HTML. It raised JSONDecodeError or returned an empty list for every
query, so venue discovery reported "no website" for restaurants whose sites
were the first result. The count was wrong at the root, not merely noisy.
"""
import os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import json, pytest
from src.brightdata import _unwrap, _real_url


def test_parsed_serp_is_returned_directly():
    doc = {"general": {"query": "Benu"}, "organic": [{"link": "https://benusf.com/"}]}
    assert _unwrap(json.dumps(doc))["organic"][0]["link"] == "https://benusf.com/"


def test_envelope_wrapping_parsed_json_is_unwrapped():
    inner = json.dumps({"general": {}, "organic": [{"link": "https://x.com/"}]})
    assert _unwrap(json.dumps({"status_code": 200, "body": inner}))["organic"]


def test_html_shell_raises_so_callers_retry():
    # This exact response is what an empty/blocked zone returns. Treating it as
    # "no results" is what made an outage permanent in the discovery cache.
    shell = json.dumps({"status_code": 200, "body": "<!doctype html><html>..."})
    with pytest.raises(ValueError):
        _unwrap(shell)


def test_bare_html_raises():
    with pytest.raises(ValueError):
        _unwrap("<!doctype html><html></html>")


def test_direct_link_is_preferred():
    assert _real_url({"link": "https://benusf.com/"}) == "https://benusf.com/"


def test_goto_link_recovers_host_from_display_link():
    # Roughly three quarters of organic hits arrive as /goto?url=<opaque>.
    # Dropping them discarded most of every SERP.
    o = {"link": "https://www.google.com/goto?url=CAESWAHEIkXX",
         "display_link": "https://www.benusf.com › reservations",
         "source": "benusf.com"}
    assert _real_url(o) == "https://www.benusf.com/"


def test_goto_link_falls_back_to_source_when_display_link_is_odd():
    o = {"link": "https://www.google.com/goto?url=CAES",
         "display_link": "", "source": "zunicafe.com"}
    assert _real_url(o) == "https://zunicafe.com/"


def test_goto_link_with_no_recoverable_host_is_dropped():
    # No display_link and no usable source: an unusable entry, not a URL.
    assert _real_url({"link": "https://www.google.com/goto?url=CAES"}) == ""


def test_source_that_is_a_venue_name_not_a_domain_is_rejected():
    assert _real_url({"link": "https://www.google.com/goto?url=x",
                      "source": "Benu"}) == ""


def test_google_hosts_never_survive_as_a_venue_site():
    for host in ("https://www.google.com/", "https://guide.michelin.com/"):
        assert _real_url({"link": host}) == host  # unwrapping is not filtering
