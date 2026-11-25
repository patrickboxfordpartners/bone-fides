"""The graph builder's rules, on small hand-made moves (plan section 16).

Every rule the Tree view depends on is locked here against synthetic data:
the gate, the named-person and named-kitchen filters, the identity rules,
the same-brand hop exclusion, the star join, mentor credit, Bay Area counts
and the slug rule. Two builds of the same input must be identical.
"""
import copy
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
from src import dossier, graph_build  # noqa: E402


def _move(person="Alex Rivera", frm=None, to=None, evidence="Alex Rivera joins the kitchen",
          **kw):
    row = {"person": person, "from_venue": frm, "to_venue": to,
          "role": "chef", "action": "JOINED", "confidence": "high",
          "evidence": evidence, "source": "eater",
          "source_url": "https://sf.eater.com/x"}
    row.update(kw)
    return row


def _starred(name, stars=1, lineage_name=None):
    return {"name": name, "lineage_name": lineage_name or name,
            "michelin": True, "stars": stars, "star_name": name}


def _build(edges, starred=None):
    return graph_build.build(edges, starred_rows=starred or [])


# ── the gate and the filters ─────────────────────────────────────────────────

def test_a_quotation_with_no_career_statement_is_dropped():
    g = _build([_move(evidence="Alex Rivera likes the pasta at Quince")])
    assert g["summary"]["dropped"]["gate"] == 1
    assert g["summary"]["moves_kept"] == 0


def test_promoted_without_a_promotion_word_is_dropped():
    g = _build([_move(evidence="Alex Rivera is now chef de cuisine at Quince",
                      action="PROMOTED")])
    assert g["summary"]["moves_kept"] == 0


def test_a_guest_chef_quotation_is_dropped():
    g = _build([_move(evidence="a guest chef appearance of Alex Rivera at Quince")])
    assert g["summary"]["moves_kept"] == 0


def test_a_cue_after_character_220_still_passes():
    padding = "The menu is long and thoughtful. " * 9
    g = _build([_move(evidence=padding + "Alex Rivera, former Quince sous chef, pours.",
                      frm="Quince", to=None)])
    assert g["summary"]["moves_kept"] == 1


def test_unnamed_persons_are_dropped():
    g = _build([_move(person="sous chef", frm="Quince", to=None,
                      evidence="The sous chef joins Quince"),
               _move(person="a duo of chefs", frm="Quince", to=None,
                     evidence="a duo of chefs joins Quince")])
    assert g["summary"]["dropped"]["unnamed_person"] == 2
    assert g["summary"]["moves_kept"] == 0


# ── is_named_kitchen ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["Hilda and Jesse", "Sons & Daughters",
                                  "The Progress", "mc²", "Quince"])
def test_named_kitchens_are_kept(name):
    assert dossier.is_named_kitchen(name) is True


@pytest.mark.parametrize("name", ["a restaurant in Marin County",
                                  "his own restaurant", "unnamed project",
                                  "luxury yachts", "252 California St.",
                                  "Town Hall, Salt House, Anchor & Hope"])
def test_descriptors_and_lists_are_dropped(name):
    assert dossier.is_named_kitchen(name) is False


# ── identity ─────────────────────────────────────────────────────────────────

def test_spellings_of_one_kitchen_are_one_node():
    edges = [_move(frm="The French Laundry", to="Benu",
                   evidence="Alex Rivera worked at the French Laundry and joins Benu"),
             _move(frm="French Laundry", to=None,
                   evidence="Alex Rivera, formerly of French Laundry")]
    g = _build(edges)
    names = [k[1] for k in g["kitchens"]]
    assert sum("French Laundry" in n for n in names) == 1


def test_locations_rulings_keep_cities_apart():
    edges = [_move(frm="Stars (Seattle)", to=None,
                   evidence="Alex Rivera worked at Stars in Seattle"),
             _move(frm="Stars (San Francisco)", to=None,
                   evidence="Alex Rivera worked at Stars in San Francisco")]
    g = _build(edges)
    assert len(g["kitchens"]) == 2


def test_a_move_between_two_spellings_of_one_kitchen_is_not_a_hop():
    edges = [_move(frm="Jardinière", to="Jardiniere",
                   evidence="Alex Rivera worked at Jardinière then Jardiniere")]
    g = _build(edges)
    assert g["summary"]["hops"] == 0


def test_the_same_brand_rule_drops_relocations():
    edges = [_move(frm="Slanted Door (Valencia Street)",
                   to="Slanted Door (Ferry Building Marketplace)",
                   evidence="Alex Rivera worked at Slanted Door on Valencia Street "
                            "then at the Slanted Door Ferry Building")]
    g = _build(edges)
    assert g["summary"]["hops"] == 0
    assert g["summary"]["dropped"]["same_brand"] == 1


def test_the_star_join_goes_through_lineage_name():
    edges = [_move(frm="Restaurant Naides", to=None,
                   evidence="Alex Rivera joins Restaurant Naides")]
    starred = [_starred("Naides", 1, lineage_name="Restaurant Naides")]
    g = _build(edges, starred)
    star = [k for k in g["kitchens"] if "Naides" in k[1]]
    assert star and star[0][3] == 1


# ── people ──────────────────────────────────────────────────────────────────

def test_two_unconnected_bodies_of_work_stay_two_people():
    # two MULTI-move bodies under one name stay two people (a lone mention
    # is not evidence of a second chef: it folds, by the dossier rule)
    a = _move(person="Jen Biesty", frm="A16", to=None, evidence="Jen Biesty worked at A16")
    a2 = _move(person="Jen Biesty", frm="Bar Agricole", to=None,
                evidence="Jen Biesty worked at Bar Agricole")
    b = _move(person="Jen Biesty", frm="Mister Jius", to=None,
              evidence="Jen Biesty worked at Mister Jius", source_url="https://sf.eater.com/y")
    b2 = _move(person="Jen Biesty", frm="Verjus", to=None,
               evidence="Jen Biesty worked at Verjus", source_url="https://sf.eater.com/y")
    g = _build([a, a2, b, b2])
    ids = [p[0] for p in g["people"]]
    assert len(ids) == 2 and ids[0].split("~")[0] == ids[1].split("~")[0]


def test_nickname_siblings_with_a_shared_kitchen_are_one_person():
    a = _move(person="Jen Biesty", frm="A16", to=None, evidence="Jen Biesty worked at A16")
    b = _move(person="Jennifer Biesty", frm="A16", to=None,
              evidence="Jennifer Biesty also worked at A16", source_url="https://sf.eater.com/y")
    g = _build([a, b])
    assert len(g["people"]) == 1


# ── mentor credit ───────────────────────────────────────────────────────────

def test_mentor_credit_needs_the_surname_in_the_quote():
    a = _move(frm="A16", to="Benu", mentor="Thomas Keller",
              evidence="Alex Rivera worked under Thomas Keller then joins Benu")
    b = _move(frm="A16", to="Coi", mentor="Thomas Keller",
              evidence="Alex Rivera joins Coi after cooking", source_url="https://sf.eater.com/z")
    c = _move(frm="A16", to="Delfina", mentor="null",
              evidence="Alex Rivera, trained by Thomas Keller, joins Delfina",
              source_url="https://sf.eater.com/w")
    g = _build([a, b, c])
    assert g["summary"]["mentor_moves"] == 1


# ── Bay Area ─────────────────────────────────────────────────────────────────

def test_oakland_counts_and_the_richmond_does_not():
    edges = [_move(frm="A16", to="Oakland Place", evidence="Alex Rivera joins Oakland Place after A16"),
             _move(frm="Benu", to="Coi", evidence="Alex Rivera worked in the Richmond",
                   source_url="https://sf.eater.com/r")]
    g = _build(edges)
    towns = dict(g["summary"]["bay_area"]["towns"])
    assert towns.get("Oakland") == 1
    assert "Richmond" not in towns


def test_a_restaurant_at_a_museum_is_a_kitchen():
    # the museum is a location note, not the venue: Cafe Ohlone at the
    # Hearst Museum and the Broad's stand-alone restaurant stay
    edges = [_move(person="Vincent Medina", frm="Cafe Ohlone (Phoebe A. Hearst Museum of Anthropology courtyard)", to=None,
                   evidence="Vincent Medina worked at Cafe Ohlone (Phoebe A. Hearst Museum)"),
             _move(person="Timothy Hollingsworth", frm="The French Laundry", to="Broad Museum restaurant",
                   evidence="Timothy Hollingsworth joined Broad Museum restaurant from the French Laundry",
                   source_url="https://sf.eater.com/h")]
    g = _build(edges)
    names = [k[1] for k in g["kitchens"]]
    assert any("Cafe Ohlone" in n for n in names)
    assert any("Broad Museum restaurant" in n for n in names)
    assert g["summary"]["dropped"]["venue_kind"] == 0


def test_a_museum_appointment_is_not_a_kitchen():
    edges = [_move(person="Bryant Terry", frm="Museum of the African Diaspora", to=None,
                   evidence="Bryant Terry worked at the Museum of the African Diaspora")]
    g = _build(edges)
    assert g["summary"]["moves_kept"] == 0
    assert g["summary"]["dropped"]["venue_kind"] == 1


def test_shows_fail_the_venue_kind_check_not_named_kitchen():
    assert dossier.is_named_kitchen("Top Chef") is True
    assert dossier._is_show_or_event_venue("Top Chef") is True


def test_an_anchor_counts_only_quotations_that_name_its_town():
    edges = [_move(frm="The French Laundry", to=None,
                   evidence="Alex Rivera worked at the French Laundry"),
             _move(frm="The French Laundry", to=None,
                   evidence="Alex Rivera worked at the French Laundry in Yountville",
                   source_url="https://sf.eater.com/y2")]
    g = _build(edges)
    anchors = g["summary"]["bay_area"]["anchors"]
    fl = [a for a in anchors if a["name"] == "The French Laundry"]
    assert fl and fl[0]["moves"] == 2 and fl[0]["quotes_naming_town"] == 1


# ── determinism ─────────────────────────────────────────────────────────────

def test_every_slug_resolves_to_its_own_node():
    edges = [_move(frm="The French Laundry", to="Benu",
                   evidence="Alex Rivera worked at the French Laundry and joins Benu"),
             _move(frm="State Bird Provisions", to="The Progress",
                   evidence="Alex Rivera joins The Progress from State Bird Provisions",
                   source_url="https://sf.eater.com/sbp")]
    g = _build(edges)
    for key, name, slug, stars, _ in g["kitchens"]:
        hit = dossier.venue_key(slug)
        assert hit is None or hit == key, (name, slug)


def test_two_builds_of_the_same_input_are_identical():
    edges = [_move(frm="Quince", to="Benu",
                   evidence="Alex Rivera joins Benu after Quince"),
             _move(person="Devin McDavid", frm="The French Laundry", to="Quince",
                   evidence="Devin McDavid joins Quince from The French Laundry",
                   source_url="https://sf.eater.com/mcdavid")]
    starred = [_starred("Quince", 3)]
    a = _build(copy.deepcopy(edges), starred)
    b = _build(copy.deepcopy(edges), starred)
    a["built_at"] = b["built_at"] = ""
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
