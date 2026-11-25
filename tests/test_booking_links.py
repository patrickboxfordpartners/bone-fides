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
    assert bvb.clean_name("Fior D'Italia") == "fior d italia"


def test_accepts_the_venues_own_sf_page():
    assert bvb.verified("opentable", "https://www.opentable.com/r/tosca-cafe-san-francisco", ["tosca cafe"])
    assert bvb.verified("opentable", "https://www.opentable.com/r/the-brixton-san-francisco", ["brixton"])
    assert bvb.verified("opentable", "https://www.opentable.com/gary-danko", ["gary danko"])


def test_accepts_a_slug_that_runs_the_name_together():
    assert bvb.verified("tock", "https://www.exploretock.com/garydanko", ["gary danko"])
    assert bvb.verified("tock", "https://www.exploretock.com/zunicafe/", ["zuni cafe"])
    # "sf" joined to the name is San Francisco, not an unknown word
    assert bvb.verified("tock", "https://www.exploretock.com/trestlesf", ["trestle"])
    assert not bvb.verified("tock", "https://www.exploretock.com/trestlenapa", ["trestle"])
    # a non-possessive apostrophe may be split or joined in the slug
    assert bvb.verified("opentable", "https://www.opentable.com/fior-d-italia-san-francisco", [bvb.clean_name("Fior D'Italia")])
    assert bvb.verified("opentable", "https://www.opentable.com/r/lardoise-san-francisco", [bvb.clean_name("L'Ardoise")])
    # one real word plus a single letter is not distinctive without a city
    assert not bvb.verified("opentable", "https://www.opentable.com/lardoise", [bvb.clean_name("L'Ardoise")])
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


def test_the_page_city_decides_for_a_city_less_url():
    url = "https://www.opentable.com/black-cat"
    assert not bvb.verified("opentable", url, ["black cat"], {url: "Longmont, CO"})
    assert bvb.verified("opentable", url, ["black cat"], {url: "San Francisco"})
    # a one-word name needs the page to confirm San Francisco
    hearth = "https://www.opentable.com/r/hearth"
    assert not bvb.verified("opentable", hearth, ["hearth"], {})
    assert bvb.verified("opentable", hearth, ["hearth"], {hearth: "San Francisco"})


def test_city_of_reads_the_restaurant_address_not_reviewers():
    spec = importlib.util.spec_from_file_location(
        "check_booking_cities", os.path.join(_ROOT, "scripts", "check_booking_cities.py"))
    cbc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cbc)
    assert cbc.city_of("123 51st St, Longmont, CO 80302 ... San Francisco12 reviews") == "Longmont, CO"
    assert cbc.city_of("1 Main St, San Francisco, CA 94124") == "San Francisco"
    assert cbc.city_of("Reviewer from San Francisco3 reviews") is None
    assert cbc.city_of("200 Linden Ave, South San Francisco, CA 94080") == "South San Francisco, CA"
    assert cbc.city_of("Best tacos in South San Francisco") is None
    assert cbc.city_of("200 Linden Ave, South  San Francisco, CA 94080") == "South San Francisco, CA"
    assert cbc.city_of("200 Linden Ave, South\nSan Francisco, CA 94080") == "South San Francisco, CA"
    assert cbc.city_of("Best tacos in South \n San Francisco") is None


def test_pending_includes_city_less_urls_the_name_fallback_would_accept(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "check_booking_cities_p", os.path.join(_ROOT, "scripts", "check_booking_cities.py"))
    cbc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cbc)
    links = {"Black Cat": {"opentable": "https://www.opentable.com/black-cat"},
             "Tosca Cafe": {"opentable": "https://www.opentable.com/r/tosca-cafe-san-francisco"}}
    monkeypatch.setattr(cbc.bvb, "build", lambda **kw: (links, []))
    assert cbc.pending({}) == ["https://www.opentable.com/black-cat"]
    assert cbc.pending({"https://www.opentable.com/black-cat": "Longmont, CO"}) == []


def test_shipped_file_has_no_link_the_page_places_elsewhere():
    cities = bvb.load_cities()
    booking = json.load(open(os.path.join(_ROOT, "ui", "venue_booking.json")))
    elsewhere = [u for links in booking.values() for u in links.values()
                 if cities.get(u) not in (None, "San Francisco")]
    assert not elsewhere, elsewhere


def test_tavily_accept_prefers_an_sf_url_over_a_city_less_one():
    spec = importlib.util.spec_from_file_location(
        "find_booking_tavily_t", os.path.join(_ROOT, "scripts", "find_booking_tavily.py"))
    fbt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fbt)
    urls = ["https://www.opentable.com/black-cat",
            "https://www.opentable.com/r/black-cat-san-francisco?lang=es"]
    assert fbt.accept(urls, {"name": "Black Cat"}) == {
        "opentable": "https://www.opentable.com/r/black-cat-san-francisco"}
    assert fbt.accept(urls[:1], {"name": "Black Cat"}) == {"opentable": urls[0]}


def test_city_checker_saves_after_every_batch(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "check_booking_cities_s", os.path.join(_ROOT, "scripts", "check_booking_cities.py"))
    cbc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cbc)
    out = tmp_path / "cities.json"
    monkeypatch.setattr(cbc.bvb, "CITIES", str(out))
    monkeypatch.setattr(cbc.bvb, "load_cities", lambda: {})
    monkeypatch.setattr(cbc.tavily, "_load_key", lambda: "k")
    monkeypatch.setattr(cbc, "pending", lambda c: [f"https://www.opentable.com/x{i}" for i in range(7)])
    calls = []

    def fake_extract(key, urls, depth="basic"):
        calls.append(urls)
        if len(calls) > 1:
            raise TimeoutError("second batch fails")
        return {u: "San Francisco" for u in urls}

    monkeypatch.setattr(cbc, "extract", fake_extract)
    try:
        cbc.main()
    except TimeoutError:
        pass
    assert len(json.loads(out.read_text())) == 5, "the finished first batch must be on disk"


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


def test_dossier_booking_is_verified_against_the_dossier_name():
    """The map links "Palette Tea House" to the lineage "Palette" (a different,
    closed restaurant) and "Camino Alto" to "Camino" (Oakland). A dossier gets
    a pin's page only when the URL names the dossier's own kitchen."""
    dossiers = json.load(open(os.path.join(_ROOT, "ui", "dossier_booking.json")))
    assert dossiers, "ui/dossier_booking.json is empty; run scripts/build_venue_booking.py"
    for wrong in ("Palette", "Camino", "Balboa", "Laguna", "Catch"):
        assert wrong not in dossiers, wrong
    assert "opentable" in dossiers["Palette Tea House"] and "resy" in dossiers["Camino Alto"]
    cities = bvb.load_cities()
    for name, links in dossiers.items():
        for platform, url in links.items():
            assert bvb.verified(platform, url, [bvb.clean_name(name)], cities), (name, url)


def test_build_dossiers_rejects_a_lineage_name_the_url_does_not_name(monkeypatch):
    pins = {"Palette Tea House": {"opentable": "https://www.opentable.com/r/palette-tea-house-san-francisco"},
            "Kin Khao Thai Eatery": {"resy": "https://resy.com/cities/san-francisco-ca/venues/kin-khao"}}
    monkeypatch.setattr(bvb.dossier, "venues_geo", lambda: [
        {"name": "Palette Tea House", "lineage_name": "Palette"},
        {"name": "Kin Khao Thai Eatery", "lineage_name": "Kin Khao"}])
    out = bvb.build_dossiers(pins, {})
    assert "Palette" not in out and "Palette Tea House" in out
    assert out["Kin Khao"] == pins["Kin Khao Thai Eatery"]
    assert "Kin Khao Thai Eatery" not in out, "/venues/kin-khao does not name the longer pin name's extra words"


def test_search_payload_carries_booking_only_for_a_resolved_dossier(monkeypatch):
    monkeypatch.setattr(dossier, "lineage", lambda es, q, **kw: [])
    monkeypatch.setattr(dossier, "fetch_person_edges", lambda es, names: [])
    for resolved, expect in ((True, True), (False, False)):
        monkeypatch.setattr(dossier, "assemble_dossier", lambda q, lin, **kw: {"query": q, "resolved": resolved})
        status, _, body = dossier.dispatch("/api/search", "q=Zuni+Caf%C3%A9", "bk" + str(resolved), client=lambda: object())
        payload = json.loads(body)
        assert status == 200 and ("booking" in payload) is expect
    assert dossier.dossier_booking("Zuni Café") == dossier.dossier_booking("zuni cafe")
    assert dossier.dossier_booking("Palette") is None and dossier.dossier_booking("") is None


def test_booking_lookup_does_not_follow_branch_aliases():
    """venue_key() merges branches for lineage ("A16 Oakland" -> A16). The
    booking lookup must not: the Oakland dossier would offer the SF room."""
    assert dossier.venue_key("A16 Oakland") == dossier.venue_key("A16"), "fixture: the alias table merges these"
    assert dossier.dossier_booking("A16")
    for branch in ("A16 Oakland", "Balboa Café Mill Valley", "Balboa Cafe Mill Valley"):
        assert dossier.dossier_booking(branch) is None, branch
    assert dossier.dossier_booking("Balboa Café") == dossier.dossier_booking("Balboa Cafe")
    # no lookup may return a page that does not verify for the name asked
    cities = bvb.load_cities()
    names = json.load(open(os.path.join(_ROOT, "ui", "dossier_booking.json")))
    for name in list(names) + ["A16 Oakland", "Balboa Café Mill Valley"]:
        for platform, url in (dossier.dossier_booking(name) or {}).items():
            assert bvb.verified(platform, url, [bvb.clean_name(name)], cities), (name, url)


def test_map_popup_uses_verified_links_not_a_resy_search():
    js = open(os.path.join(_ROOT, "ui", "map.js")).read()
    assert "resy.com/city" not in js
    assert "v.booking" in js
