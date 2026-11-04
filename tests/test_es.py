from src.es import build_edge_doc, INDEX_SETTINGS

EDGE = {"person": "Alexander Ong", "from_venue": "Betelnut", "to_venue": None,
        "role": "executive chef", "date": "2001-2013",
        "evidence": "Ong departs", "confidence": "high",
        "source_url": "https://sf.eater.com/x"}

def test_edge_doc_has_citation_and_names():
    d = build_edge_doc(EDGE)
    assert d["person"] == "Alexander Ong"
    assert d["source_url"] == "https://sf.eater.com/x"
    assert d["evidence"] == "Ong departs"

def test_edge_doc_inferable_for_text_fields():
    d = build_edge_doc(EDGE)
    # text copies for fuzzy keyword search + semantic field declared in settings
    assert "person_text" in d and "venue_text" in d
    assert d["venue_text"] == "Betelnut executive chef" or "Betelnut" in d["venue_text"]

def test_settings_declare_semantic_text_field():
    m = INDEX_SETTINGS["mappings"]["properties"]
    assert "semantic" in m
    assert m["semantic"]["type"] == "semantic_text"
