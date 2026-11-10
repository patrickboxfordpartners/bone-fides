"""Tip intake: the inbox accepts what a human can act on and rejects the rest.

The tips index is a queue, not the corpus — these tests hold the intake
validator to the citation-first standard the corpus itself is held to.
"""
from ui.server import accept_tip


def _good(**over):
    p = {"type": "add a source", "url": "https://sf.eater.com/2020/ssal",
         "note": "covers the opening", "query": "Ssal", "website": ""}
    p.update(over)
    return p


def test_valid_tip_becomes_a_storable_doc():
    ok, doc = accept_tip(_good(), "1.2.3.4")
    assert ok is True
    assert doc["type"] == "add a source"
    assert doc["url"] == "https://sf.eater.com/2020/ssal"
    assert doc["note"] == "covers the opening"
    assert doc["ip"] == "1.2.3.4"
    assert doc["status"] == "open"
    assert doc["created_at"]  # timestamped for the triage sort


def test_wrong_detail_needs_note_or_url():
    ok, err = accept_tip({"type": "wrong detail", "note": "   ", "website": ""}, "1.2.3.4")
    assert ok is False
    assert err == "a note or a source link is required"


def test_url_is_required_to_grow_the_record():
    # a move with no citation is not actionable; citations are the product
    ok, err = accept_tip({"type": "add a move", "note": "he worked there", "website": ""}, "ip")
    assert ok is False
    assert err == "a source link is required to add to the record"
    # non-URL strings do not count as a link
    ok, err = accept_tip({"type": "add a source", "url": "read the chronicle", "website": ""}, "ip")
    assert ok is False
    assert err == "a source link is required to add to the record"
    # wrong-detail flags are fine without one
    ok, doc = accept_tip({"type": "wrong detail", "note": "date is off", "website": ""}, "ip")
    assert ok is True and doc["type"] == "wrong detail"


def test_unknown_type_rejected():
    ok, err = accept_tip(_good(type="free pizza"), "ip")
    assert ok is False and err == "unknown type"


def test_honeypot_accepted_but_never_stored():
    ok, doc = accept_tip(_good(website="http://spam.example"), "ip")
    assert ok is True and doc is None  # silent accept, no doc
    # whitespace-only honeypot is still an empty honeypot
    ok, doc = accept_tip(_good(website="  "), "ip")
    assert ok is True and doc is not None


def test_field_caps():
    url = "https://sf.eater.com/" + "a" * 400
    ok, doc = accept_tip(_good(url=url, note="n" * 900), "ip")
    assert ok is True
    assert len(doc["url"]) == 300
    assert len(doc["note"]) == 500


def test_non_dict_payload():
    ok, err = accept_tip("not a dict", "ip")
    assert ok is False and err == "invalid payload"
