"""Entity-scoped dossiers, conservative identity, and outlet labels.

These lock the post-resolution bugs: a search page is not a kitchen's
record, Dan is not Danielle, and joecontent.net is not Eater.
"""
from ui.server import (
    _fuzzy_sibling, _venue_touch, allow_request, assemble_dossier,
    citation_supported, clamp_size, identity, outlet_tier,
)


def _move(person, frm, to, evidence, **kw):
    row = {
        "person": person, "from_venue": frm, "to_venue": to,
        "role": "chef", "action": "JOINED", "confidence": "high",
        "evidence": evidence, "source": "eater",
        "source_url": "https://sf.eater.com/x",
    }
    row.update(kw)
    return row


def test_page_of_noise_does_not_score_as_the_kitchen():
    edges = []
    for i in range(22):
        edges.append(_move(f"P{i}", "Elsewhere", "Other Kitchen",
                           "left Elsewhere to join Other Kitchen",
                           source_url=f"https://sf.eater.com/{i}"))
    for i in range(3):
        edges.append(_move(f"H{i}", "Hutong", "Betelnut",
                           "left Hutong to join Betelnut",
                           source="sfgate", source_url=f"https://www.sfgate.com/h{i}"))
    d = assemble_dossier("Hutong", edges)
    assert d["resolved"] is True
    assert d["pedigree"]["moves"] == 3
    assert len(d["lineage"]) == 3
    assert {e["person"] for e in d["lineage"]} == {"H0", "H1", "H2"}


def test_unresolved_query_returns_no_dossier():
    edges = [_move("Tanya Holland", None, "Brown Sugar Kitchen",
                   "left the kitchen at Brown Sugar Kitchen")]
    d = assemble_dossier("zzzz nonexistent kitchen 2026", edges)
    assert d["resolved"] is False
    assert d["lineage"] == []
    assert d["identity"] == []
    assert d["pedigree"] is None


def test_recipe_sentence_is_not_a_high_confidence_promotion():
    butter = ("Gitane executive chef Bridget Batson combines it with butter "
              "to make this quick, unusual dish.")
    edges = [
        _move("Bridget Batson", "Gitane", None, butter,
              action="PROMOTED", role="executive chef", source="sfgate",
              source_url="https://www.sfgate.com/butter"),
        _move("Bridget Batson", "Gitane", "Munchery",
              "Gitane chef Bridget Batson left the restaurant to join Munchery",
              action="DEPARTED", source="eater",
              source_url="https://sf.eater.com/leave"),
    ]
    assert citation_supported(edges[0]) is False
    d = assemble_dossier("Gitane", edges)
    assert d["pedigree"]["moves"] == 1
    assert d["lineage"][0]["to_venue"] == "Munchery"
    assert "butter" not in d["lineage"][0]["evidence"]


def test_unknown_host_is_not_eater():
    assert outlet_tier(None, "https://www.joecontent.net/china-live") == "other"
    assert outlet_tier(None, "https://www.potatoglory.com/ong") == "other"
    assert outlet_tier(None, "https://asian-fusion.com/ong") == "other"
    assert outlet_tier("eater", "https://www.joecontent.net/x") == "other"
    assert outlet_tier(None, "https://sf.eater.com/x") == "eater"
    assert outlet_tier("sfgate", "https://www.sfgate.com/x") == "sfgate"
    edge = _move("George Chen", None, "Betelnut",
                 "opened Betelnut in 1995",
                 source=None, source_url="https://www.joecontent.net/chen")
    d = assemble_dossier("Betelnut", [edge])
    assert d["lineage"][0]["outlet"] == "other"
    assert d["pedigree"]["tiers"]["eater"] == 0
    assert d["pedigree"]["tiers"]["other"] == 1


def test_dan_and_danielle_stay_distinct():
    assert _fuzzy_sibling("dan smith", "danielle smith") is False
    edges = [
        _move("Dan Smith", "Gitane", "Cotogna", "left Gitane to join Cotogna",
              source_url="https://sf.eater.com/dan1"),
        _move("Dan Smith", "Cotogna", "Nari", "left Cotogna to join Nari",
              source_url="https://sf.eater.com/dan2"),
        _move("Danielle Smith", "Gitane", "Spruce", "left Gitane to join Spruce",
              source_url="https://sf.eater.com/danielle1"),
        _move("Danielle Smith", "Spruce", "Quince", "left Spruce to join Quince",
              source_url="https://sf.eater.com/danielle2"),
    ]
    names = {c["name"] for c in identity(edges)}
    assert names == {"Dan Smith", "Danielle Smith"}
    assert all("Danielle Smith" not in c["aliases"] for c in identity(edges))


def test_nickname_pairs_still_match_and_generic_venues_do_not():
    assert _fuzzy_sibling("jen biesty", "jennifer biesty") is True
    assert _fuzzy_sibling("chris lee", "christopher lee") is True
    assert _fuzzy_sibling("chris lee", "christina lee") is False
    assert _venue_touch("bar", "bar tartine") is False
    assert _venue_touch("san", "san ho won") is False
    assert _venue_touch("betelnut", "betelnut pejiu wu") is True
    assert _venue_touch("ritz carlton", "ritz carlton buckhead") is True


def test_punctuation_loose_resolution():
    """A reader who drops the apostrophe ("Mister Jius") or the plus
    ("flour water") still gets the kitchen's dossier."""
    edges = [
        _move("Brandon Jew", "Mister Jiu's", "Jew Fong Supper Club",
              "Mister Jiu's chef de cuisine Brandon Jew left to join Jew Fong Supper Club"),
        _move("Eve Aronoff", "flour + water", "Coesa",
              "flour + water sous chef Eve Aronoff left to join Coesa"),
    ]
    for q in ("Mister Jiu's", "Mister Jius", "mister jiu s"):
        d = assemble_dossier(q, edges)
        assert d["resolved"] is True, q
        assert len(d["lineage"]) == 1, q
    for q in ("flour + water", "flour water", "flourwater"):
        d = assemble_dossier(q, edges)
        assert d["resolved"] is True, q
        assert len(d["lineage"]) == 1, q
    # short keys stay gated: 3 loose chars must not absorb everything
    assert assemble_dossier("benu", edges)["resolved"] is False
    # distinct kitchens stay distinct once punctuation is dropped
    assert assemble_dossier("banchan vendrs", edges)["resolved"] is False


def test_size_cap_and_rate_limit():
    assert clamp_size(None) == 25
    assert clamp_size("") == 25
    assert clamp_size([]) == 25
    assert clamp_size(999) == 40
    assert clamp_size("1") == 1
    key = "test-size-cap"
    assert allow_request("search", key, 2, 60, now=1000) is True
    assert allow_request("search", key, 2, 60, now=1001) is True
    assert allow_request("search", key, 2, 60, now=1002) is False
    assert allow_request("search", key, 2, 60, now=1061) is True
