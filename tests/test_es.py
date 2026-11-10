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

def test_edge_doc_stamps_role_bucket():
    # index-time stamp (roadmap 4.3): &role= filters on this keyword field
    d = build_edge_doc(EDGE)
    assert d["role_bucket"] == "executive chef"
    assert d["role"] == "executive chef"  # raw text kept for display

def test_find_edges_role_filter_is_post_filter():
    # post_filter, not a retriever-level clause: it gates the final RRF hit
    # list without touching ranking, and this ES version rejects
    # sparse_vector nested inside bool
    import inspect
    from src.es import find_edges
    src = inspect.getsource(find_edges)
    assert 'post_filter' in src
    assert '{"term": {"role_bucket": role}}' in src
