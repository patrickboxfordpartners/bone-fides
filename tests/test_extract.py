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
        {"person": "X", "from_venue": "A", "role": "chef", "evidence": "joined the kitchen", "confidence": "high"},
        {"person": None, "from_venue": "A", "role": "chef", "evidence": "joined the kitchen", "confidence": "high"},
        {"person": "Y", "from_venue": None, "role": "chef", "evidence": "joined the kitchen", "confidence": "high"},
    ]}
    assert len(parse_extraction(raw)) == 1  # only first has both

def test_parse_rejects_low_confidence():
    raw = {"edges": [{"person": "X", "from_venue": "A", "role": "chef",
                      "evidence": "joined the kitchen", "confidence": "low"}]}
    assert parse_extraction(raw) == []

def test_parse_drops_empty_guest_and_recipe_promotion():
    raw = {"edges": [
        {"person": "A", "from_venue": "Gitane", "role": "chef", "action": "JOINED",
         "evidence": "", "confidence": "high"},
        {"person": "B", "from_venue": "Central Kitchen", "to_venue": "Sprig",
         "role": "guest chefs", "action": "JOINED",
         "evidence": "guest chefs joined the program", "confidence": "high"},
        {"person": "Bridget Batson", "from_venue": "Gitane", "role": "executive chef",
         "action": "PROMOTED", "confidence": "high",
         "evidence": "Gitane executive chef Bridget Batson combines it with butter to make this quick, unusual dish."},
        {"person": "C", "from_venue": "Gitane", "to_venue": "Munchery", "role": "chef",
         "action": "DEPARTED", "confidence": "high",
         "evidence": "Gitane chef Bridget Batson left the restaurant to join Munchery"},
    ]}
    out = parse_extraction(raw)
    assert [e["person"] for e in out] == ["C"]

def test_parse_requires_evidence_in_the_article():
    article = "TITLE: Gitane chef Bridget Batson left the restaurant to join Munchery."
    raw = {"edges": [{
        "person": "Bridget Batson", "from_venue": "Gitane", "to_venue": "Munchery",
        "role": "chef", "action": "DEPARTED", "confidence": "high",
        "evidence": "she was promoted last spring",
    }]}
    assert parse_extraction(raw, article_text=article) == []
    raw["edges"][0]["evidence"] = "left the restaurant to join Munchery"
    raw["edges"][0]["action"] = "DEPARTED"
    assert len(parse_extraction(raw, article_text=article)) == 1
