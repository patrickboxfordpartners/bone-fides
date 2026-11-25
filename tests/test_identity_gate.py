"""Package D: collective-entity gate + person-query detection.

The corpus honestly records unnamed people ("chefs", "sous chef", "two
chefs") — they must not resolve junk queries, and person-name venue values
(namesake restaurants, mis-extractions) must not flip person queries into
venue queries.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import dossier as _mod  # noqa: E402

resolve_query = _mod.resolve_query
_is_collective = _mod._is_collective


def test_collective_strings_flagged():
    for n in ("chefs", "sous chef", "pastry chef", "two chefs", "unnamed",
              "a duo of chefs", "line cooks", "unknown chef", "new chef"):
        assert _is_collective(n), n


def test_named_people_not_collective():
    for n in ("Daniel Patterson", "Chef Heena Patel",
              'Solomon "Chef Swoop" Johnson', "Kim family",
              "Rich Table", "top SF chefs"):
        assert not _is_collective(n), n


def test_collective_does_not_resolve_query():
    cl = [{"name": "chefs", "aliases": [], "homonym": False, "possible": [],
           "n": 1, "edges": []}]
    assert resolve_query("chefs", [], cl) is False


def test_named_person_resolves():
    cl = [{"name": "Daniel Patterson", "aliases": [], "homonym": False,
           "possible": [], "n": 51, "edges": []}]
    assert resolve_query("Daniel Patterson", [], cl) is True


def test_venue_resolution_untouched():
    edges = [{"from_venue": "Betelnut", "to_venue": None}]
    assert resolve_query("Betelnut", edges, []) is True
