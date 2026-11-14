"""The venue-site registry: human verdicts outrank SERP, and stay honest.

SERP is close to useless for a closed restaurant — it returns a dead domain, a
lookalike, or a directory page. On 2026-11-13 a human supplied 28 verdicts for
the top venues by lineage; 22 were closures. Those must be recorded as a real
answer, not retried forever, or "this place is gone" silently reads as
"no image yet" on every subsequent run.
"""
import os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import json, re
from src.venue_images import norm

REGISTRY = os.path.join(_ROOT, "ui", "venue_sites.json")


def _registry():
    return json.load(open(REGISTRY))


def test_registry_keys_are_norm_of_their_names():
    # A key that is not norm(name) would never match a venue at lookup time and
    # the verdict would be silently ignored. `closed` maps key -> display name;
    # `website` maps key -> URL, so only its keys are checkable here.
    reg = _registry()
    for key, name in reg["closed"].items():
        assert norm(name) == key, f"closed:{key} != norm({name!r})"
    for key in reg["website"]:
        assert key == norm(key), f"website key {key!r} is not already normalised"


def test_no_venue_is_both_closed_and_given_a_website():
    reg = _registry()
    both = set(reg["closed"]) & set(reg["website"])
    assert not both, f"contradictory verdicts: {sorted(both)}"


def test_known_closures_are_recorded():
    closed = _registry()["closed"]
    for name in ("Fifth Floor", "Mourad", "Oliveto", "AQ", "Elisabeth Daniel"):
        assert norm(name) in closed


def test_known_sites_are_recorded():
    sites = _registry()["website"]
    assert sites["coi"] == "https://coirestaurant.com/"
    assert sites["perse"].startswith("https://thomaskeller.com/")


def test_commis_is_resolved_and_flagged_for_broken_tls():
    # Commis serves a leaf without its intermediate. It is a live site, not a
    # closure, and the broken chain is recorded so the resolver may relax
    # verification for this host only rather than for everything.
    reg = _registry()
    assert norm("Commis") not in reg["closed"]
    assert reg["website"][norm("Commis")] == "https://commisrestaurant.com/"
    assert norm("Commis") in reg.get("broken_tls_chain", {})


def test_broken_tls_flag_only_covers_hosts_in_the_registry():
    # A broken-chain host with no recorded website would never be fetched, so
    # the pair must move together.
    reg = _registry()
    sites, broken = reg.get("website", {}), reg.get("broken_tls_chain", {})
    assert set(broken) <= set(sites), sorted(set(broken) - set(sites))


def test_parallel37_booking_only_site_is_documented():
    reg = _registry()
    # The only live presence is a reservations page for a closed restaurant;
    # recording the caveat stops a later reader treating it as an active site.
    assert "parallel37" in reg.get("booking_only", {})
