"""Map booking buttons: only verified Resy / OpenTable / Tock pages for the pin.

The map used to show "Book on Resy" for every dot, pointing at a Resy city
search. The crawl had real booking pages for hundreds of venues, but nothing
used them, and some of them were same-named restaurants in other cities.
"""
import importlib.util
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src import dossier  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "build_venue_booking", os.path.join(_ROOT, "scripts", "build_venue_booking.py"))
bvb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bvb)


def test_clean_name_drops_permit_register_noise():
    assert bvb.clean_name("Angler Sf, Llc") == "angler"
    assert bvb.clean_name("Ernest Restaurant / Befr Llc") == "ernest"
    assert bvb.clean_name("Penny Roma/Flour+Water Pasta Shop") == "penny roma"
    assert bvb.clean_name("The Brixton") == "brixton"
    assert bvb.clean_name("Schroeder's") == "schroeders"


def test_accepts_the_venues_own_sf_page():
    assert bvb.verified("opentable", "https://www.opentable.com/r/tosca-cafe-san-francisco", ["tosca cafe"])
    assert bvb.verified("opentable", "https://www.opentable.com/r/the-brixton-san-francisco", ["brixton"])
    assert bvb.verified("opentable", "https://www.opentable.com/gary-danko", ["gary danko"])


def test_accepts_a_slug_that_runs_the_name_together():
    assert bvb.verified("tock", "https://www.exploretock.com/garydanko", ["gary danko"])
    assert bvb.verified("tock", "https://www.exploretock.com/zunicafe/", ["zuni cafe"])
    # a joined name with a place word left over is still another restaurant
    assert not bvb.verified("tock", "https://www.exploretock.com/garydanko-napa", ["gary danko"])


def test_rejects_a_same_named_restaurant_elsewhere():
    for url, names in (
        ("https://www.opentable.com/r/la-victoria-tampa", ["la victoria"]),
        ("https://www.opentable.com/r/gather-berkeley", ["gather"]),
        ("https://resy.com/cities/maryville-tn/venues/bella", ["bella"]),
        ("https://www.opentable.com/r/buon-gusto-south-san-francisco", ["gusto"]),
        ("https://www.opentable.com/r/tadich-grill-san-francisco", ["grill lobby bar"]),
    ):
        assert not bvb.verified("opentable" if "opentable" in url else "resy", url, names), url


def test_a_url_without_a_city_needs_the_pins_own_multiword_name():
    # one word and no city: Kaya, Sasa and Hearth are restaurants in other towns too
    assert not bvb.verified("opentable", "https://www.opentable.com/kaya", ["kaya house", "kaya"])
    assert not bvb.verified("opentable", "https://www.opentable.com/r/hearth", ["hearth"])
    assert not bvb.verified("opentable", "https://www.opentable.com/r/schroeders", [bvb.clean_name("Schroeder's")])
    # the lineage name (second entry) cannot vouch for a city-less page
    assert not bvb.verified("opentable", "https://www.opentable.com/r/the-richmond", ["richmond market", "the richmond"])


def test_lineage_name_cannot_vouch_for_the_pin():
    # "Balboa Produce" (a market) is linked to the corpus name "Balboa";
    # Balboa Cafe's page must not become the market's booking button.
    assert not bvb.verified("opentable", "https://www.opentable.com/balboa-cafe-sf", ["balboa produce"])


def test_rejects_search_and_directory_pages():
    assert not bvb.verified("resy", "https://resy.com/city/san-francisco?query=Rich%20Table", ["rich table"])
    assert not bvb.verified("opentable", "https://www.opentable.com/metro/san-francisco-restaurants", ["san francisco"])
    assert not bvb.verified("resy", "https://fake-resy.com/rich-table-san-francisco", ["rich table"])


def test_venues_api_carries_only_verified_links():
    booking = json.load(open(os.path.join(_ROOT, "ui", "venue_booking.json")))
    assert booking, "ui/venue_booking.json is empty; run scripts/build_venue_booking.py"
    venues = dossier.venues_geo()
    with_links = [v for v in venues if v.get("booking")]
    assert with_links
    for v in with_links:
        assert v["booking"] == booking[v["name"]]
        assert set(v["booking"]) <= {"resy", "opentable", "tock"}
    assert "/city/" not in json.dumps(booking) and "query=" not in json.dumps(booking)


def test_map_popup_uses_verified_links_not_a_resy_search():
    js = open(os.path.join(_ROOT, "ui", "map.js")).read()
    assert "resy.com/city" not in js
    assert "v.booking" in js
