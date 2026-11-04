from src.extract import build_edges_prompt, parse_extraction

ARTICLE = "TITLE: Betelnut closes. Chef Alexander Ong exits after 20 years."

def test_prompt_names_required_fields():
    p = build_edges_prompt(ARTICLE)
    for field in ("person", "from_venue", "to_venue", "role", "source"):
        assert field in p

def test_parse_extraction_takes_valid_edges():
    raw = {"edges": [{
        "person": "Alexander Ong", "from_venue": "Betelnut",
        "to_venue": None, "role": "executive chef", "date": "2001-2013",
        "evidence": "Named exec chef... exits",
        "confidence": "high",
    }]}
    out = parse_extraction(raw)
    assert out[0]["person"] == "Alexander Ong"
    assert out[0]["from_venue"] == "Betelnut"
    assert out[0]["confidence"] == "high"

def test_parse_drops_edges_missing_person_or_venue():
    raw = {"edges": [
        {"person": "X", "from_venue": "A", "role": "chef", "evidence": "e", "confidence": "high"},
        {"person": None, "from_venue": "A", "role": "chef", "evidence": "e", "confidence": "high"},
        {"person": "Y", "from_venue": None, "role": "chef", "evidence": "e", "confidence": "high"},
    ]}
    assert len(parse_extraction(raw)) == 1  # only first has both

def test_parse_rejects_low_confidence():
    raw = {"edges": [{"person": "X", "from_venue": "A", "role": "chef",
                      "evidence": "e", "confidence": "low"}]}
    assert parse_extraction(raw) == []
