"""Roadmap 4.4 normalizers: era buckets from loose dates, venue->hood join.

Locks the discipline: only explicit year patterns yield an era (relative
dates never lie), ranges anchor on the first year, and hoods come only
from the city file's own analysis_neighborhood labels (verified closed
venues carry a city-vocabulary label; non-SF venues stay unstamped).
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.eras import era_bucket, ERA_BUCKETS  # noqa: E402
from src.hoods import hood_for, load_hood_maps, hood_vocabulary, CLOSED_SF  # noqa: E402

# era buckets
def test_era_bare_years():
    assert era_bucket("2015") == "2010s"
    assert era_bucket("1998") == "1990s"
    assert era_bucket("2026") == "2020s"

def test_era_ranges_anchor_first_year():
    # the arrival era is the honest single value for a career move
    assert era_bucket("2010-2016") == "2010s"
    assert era_bucket("2008-2010") == "2000s"
    assert era_bucket("1976-2015") == "pre-1990"  # name-history edge

def test_era_iso_and_prose():
    assert era_bucket("2006-12-31") == "2000s"
    assert era_bucket("October 2017") == "2010s"
    assert era_bucket("fall 2017") == "2010s"
    assert era_bucket("Opened in 1995") == "1990s"

def test_era_relative_dates_stay_none():
    # no citable year -> no stamp; the facet must never invent one
    assert era_bucket("recently") is None
    assert era_bucket("this summer") is None
    assert era_bucket("end of the month") is None
    assert era_bucket("January") is None
    assert era_bucket("") is None
    assert era_bucket(None) is None

def test_era_noise_years_stay_none():
    assert era_bucket("1045") is None
    assert era_bucket("two years ago") is None

def test_era_vocabulary_shape():
    assert ERA_BUCKETS == ("pre-1990", "1990s", "2000s", "2010s", "2020s")
    # every bucket era_bucket returns is in the vocabulary
    for d in ("1926", "1989", "1990", "1999", "2000", "2009", "2010",
              "2019", "2020", "2026"):
        assert era_bucket(d) in ERA_BUCKETS

# hood join
_MAPS = load_hood_maps()

def test_hood_open_lineaged_venue():
    # flagship row of the map pin (same join the map uses)
    assert hood_for("State Bird Provisions", _MAPS) == "Western Addition"
    assert hood_for("Mister Jiu’s", _MAPS) == "Chinatown"   # curly apostrophe
    assert hood_for("Mister Jiu's", _MAPS) == "Chinatown"   # straight twin

def test_hood_permit_row_and_prefix():
    assert hood_for("Tartine Bakery", _MAPS) == "Mission"
    # unambiguous token-prefix fallback, len>=4 both sides

def test_hood_closed_venue_curation():
    # verified against the city file's own block labels, never guessed
    assert hood_for("Betelnut", _MAPS) == "Marina"
    assert hood_for("SPQR", _MAPS) == "Pacific Heights"
    assert hood_for("Jardinière", _MAPS) == "Tenderloin"
    assert hood_for("Slanted Door", _MAPS) == "Financial District/South Beach"

def test_hood_non_sf_stays_none():
    # nothing invents an SF hood for an out-of-city kitchen
    assert hood_for("Chez Panisse", _MAPS) is None
    assert hood_for("Manresa", _MAPS) is None
    assert hood_for("The French Laundry", _MAPS) is None
    assert hood_for("Per Se", _MAPS) is None

def test_hood_junk_and_empty():
    assert hood_for("", _MAPS) is None
    assert hood_for(None, _MAPS) is None
    assert hood_for("   ", _MAPS) is None

def test_hood_vocabulary_is_city_labels():
    # the facet accepts exactly the city file's labels + curated ones;
    # every CLOSED_SF value must be in the vocabulary (a curated hood the
    # facet rejects would be a silent lie)
    labels = set(hood_vocabulary())
    for h in CLOSED_SF.values():
        assert h in labels
    assert "Mission" in labels and "Marina" in labels

def test_hood_all_closed_sf_are_city_vocabulary_labels():
    # each curated label appears in the city file's analysis_neighborhood
    # values (the join never invents a 43rd neighborhood)
    import json
    cv = json.load(open(os.path.join(_ROOT, "ui", "city_venues.json")))["venues"]
    city_labels = {v.get("neighborhood") for v in cv if v.get("neighborhood")}
    for h in CLOSED_SF.values():
        assert h in city_labels
