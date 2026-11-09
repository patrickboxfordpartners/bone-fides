"""Review round-trip for PR #5 (entity scope + citation gate).

Both server implementations must behave identically: ui/server.py (local
demo) and vercel-app/api/search.py (deployed). Each test runs against the
Vercel twin via the same function handles.
"""
import importlib.util
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_vercel = _load("vercel_search", os.path.join(
    _HERE, "..", "vercel-app", "api", "search.py"))


SERVERS = [
    pytest.param(_load("ui_server", os.path.join(_HERE, "..", "ui", "server.py")),
                 id="ui/server.py"),
    pytest.param(_vercel, id="vercel-app/api/search.py"),
]


def _move(person, frm, to, evidence, **kw):
    row = {
        "person": person, "from_venue": frm, "to_venue": to,
        "role": "chef", "action": "JOINED", "confidence": "high",
        "evidence": evidence, "source": "eater",
        "source_url": "https://sf.eater.com/x",
    }
    row.update(kw)
    return row


# ── finding 1: plain career facts are citations ──

@pytest.mark.parametrize("srv", SERVERS)
def test_worked_at_is_a_citation(srv):
    assert srv.citation_supported(
        _move("Mourad Lahlou", None, "Mourad", "worked at Betelnut")) is True


@pytest.mark.parametrize("srv", SERVERS)
def test_worked_under_is_a_citation(srv):
    edge = _move("Sara Chen", "Nopa", None,
                 "She worked under Thomas Keller at French Laundry before Nopa",
                 mentor="Thomas Keller")
    assert srv.citation_supported(edge) is True


@pytest.mark.parametrize("srv", SERVERS)
@pytest.mark.parametrize("ev", [
    "trained at the French Laundry for two years",
    "apprenticed under Paul Bertolli",
    "staged at Eleven Madison Park",
    "cooked for Alice Waters at Chez Panisse",
    "his tenure at Boulevard spanned a decade",
    "sous chef under David Kinch",
    "spent six years at Zuni Cafe",
])
def test_mentor_and_stint_phrasings_are_citations(srv, ev):
    assert srv.citation_supported(_move("X", None, None, ev)) is True


@pytest.mark.parametrize("srv", SERVERS)
def test_recipe_sentence_still_fails(srv):
    # the negative case the cue list must not loosen
    assert srv.citation_supported(
        _move("Bridget Batson", "Gitane", None,
              "combines it with butter to make this quick dish",
              action="PROMOTED")) is False


# ── finding 2: full quotation is judged before the display cut ──

@pytest.mark.parametrize("srv", SERVERS)
def test_long_citation_keeps_its_move(srv):
    # the move verb sits past character 220: ingestion passes, and the
    # dossier must score the same edge instead of dropping it
    filler = ("In a long profile covering the restaurant's design-build process, "
              "the wine program assembled over three years, the tasting menu's "
              "arc through the coastal seasons, the pastry section's larder, "
              "and the dining room's harbor view, the writer finally arrives "
              "at the staff: ")
    long = filler + "the chef left Nopa to join State Bird Provisions."
    assert len(long) > 260
    edge = _move("Nicholas Bice", "Nopa", "State Bird Provisions", long)
    assert srv.citation_supported(edge) is True
    d = srv.assemble_dossier("State Bird Provisions", [edge])
    assert d["resolved"] is True
    assert d["pedigree"]["moves"] == 1
    assert len(d["lineage"][0]["evidence"]) == 220  # display cut still applied


# ── finding 3: the queried person's edges don't count against them ──

@pytest.mark.parametrize("srv", SERVERS)
def test_namesake_restaurant_does_not_steal_the_dossier(srv):
    # Michael Mina (chef): 2 own edges, one touching his namesake restaurant.
    # Two other chefs' edges touch that restaurant. Old rule: venue 3 > person
    # 2 → restaurant dossier, chef's second move dropped. Explorer's rule
    # (and the new one): 2 vs 2 → person wins.
    edges = [
        _move("Michael Mina", "Aqua", "Michael Mina", "left Aqua to open Michael Mina"),
        _move("Michael Mina", "Michael Mina", "Bourbon Steak",
              "left Michael Mina to join Bourbon Steak"),
        _move("Raj Patel", None, "Michael Mina", "joined Michael Mina as chef de cuisine"),
        _move("Kim Vo", None, "Michael Mina", "joined Michael Mina to run the bar"),
    ]
    d = srv.assemble_dossier("Michael Mina", edges)
    assert d["resolved"] is True
    people = {c["name"] for c in d["identity"]}
    assert "Michael Mina" in people
    # both of the chef's own moves survive
    assert {e["person"] for e in d["lineage"]} == {"Michael Mina"}
    assert d["pedigree"]["moves"] == 2


@pytest.mark.parametrize("srv", SERVERS)
def test_venue_query_still_wins_when_it_outnumbers(srv):
    # a real venue query with more citations than any one person still scopes
    # to the venue
    edges = [
        _move("A", None, "Hutong", "joined Hutong as chef"),
        _move("B", None, "Hutong", "joined Hutong after years in Macau"),
        _move("C", "Hutong", "Elsewhere", "left Hutong to join Elsewhere"),
        _move("D", "Elsewhere", "Hutong", "joined Hutong"),
    ]
    d = srv.assemble_dossier("Hutong", edges)
    assert d["pedigree"]["moves"] == 4
    assert {e["person"] for e in d["lineage"]} == {"A", "B", "C", "D"}


@pytest.mark.parametrize("srv", SERVERS)
def test_venue_win_keeps_the_namesake_chefs_moves(srv):
    # When the restaurant wins the count, its dossier keeps the namesake
    # chef's restaurant moves: they are part of the restaurant's record.
    # (A regression of the first exclusion fix, which dropped them.)
    edges = [
        _move("Michael Mina", "Aqua", "Michael Mina", "left Aqua to open Michael Mina"),
        _move("Michael Mina", "Michael Mina", "Bourbon Steak",
              "left Michael Mina to join Bourbon Steak"),
        _move("Raj Patel", None, "Michael Mina", "joined Michael Mina as chef de cuisine"),
        _move("Kim Vo", None, "Michael Mina", "joined Michael Mina to run the bar"),
        _move("Lee Anne", "Nopa", "Michael Mina", "joined Michael Mina after Nopa"),
    ]
    d = srv.assemble_dossier("Michael Mina", edges)
    assert d["resolved"] is True
    people = {c["name"] for c in d["identity"]}
    assert "Michael Mina" in people  # the chef keeps a card
    assert d["pedigree"]["moves"] == 5
    assert {e["person"] for e in d["lineage"]} == {
        "Michael Mina", "Raj Patel", "Kim Vo", "Lee Anne"}


# ── finding 4: accented queries keep their letters ──

@pytest.mark.parametrize("srv", SERVERS)
def test_suggest_keeps_accented_letters(srv):
    # Jardinière must not become Jardinire: the sanitizer preserves Unicode
    # letters and only escapes wildcard metacharacters
    safe = srv._suggest_safe("Jardinière")
    assert "è" in safe
    assert "*" not in safe  # wildcard chars are escaped, letters are kept


@pytest.mark.parametrize("srv", SERVERS)
def test_suggest_strips_wildcards(srv):
    for ch in ("*", "?", "]", "[", "\\"):
        assert ch not in srv._suggest_safe("a" + ch + "b")
