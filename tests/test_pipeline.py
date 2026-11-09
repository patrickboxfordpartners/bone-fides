from src.pipeline import run_pipeline

class FakeMistral:
    def __init__(self, edges):
        self.edges = edges
    def chat_parse(self, prompt):
        return {"edges": self.edges}

def test_pipeline_produces_edges_with_source_url():
    fetch = lambda url: "TITLE: t\n\nChef Ong leaves Betelnut for UMass."
    mistral = FakeMistral([{"person": "Ong", "from_venue": "Betelnut", "to_venue": None,
                            "role": "exec chef", "date": None,
                            "evidence": "leaves Betelnut", "confidence": "high"}])
    out = run_pipeline(["https://x.com/a"], fetch=fetch, extract=mistral.chat_parse, fetch_batch=True)
    assert len(out) == 1
    assert out[0]["source_url"] == "https://x.com/a"

def test_pipeline_accumulates_across_sources():
    fetch = lambda url: "TITLE: t\n\nA joined V2."
    mistral = FakeMistral([{"person": "A", "from_venue": "V1", "to_venue": "V2",
                            "role": "chef", "evidence": "joined V2", "confidence": "high"}])
    out = run_pipeline(["https://x.com/1", "https://x.com/2"], fetch=fetch,
                       extract=mistral.chat_parse)
    assert len(out) == 2
    assert out[0]["source_url"] != out[1]["source_url"]

def test_pipeline_survives_one_failed_source():
    def fetch(url):
        if url.endswith("bad"):
            raise RuntimeError("403")
        return "TITLE: t\n\nbody"
    mistral = FakeMistral([])
    out = run_pipeline(["https://x.com/bad", "https://x.com/good"], fetch=fetch,
                       extract=mistral.chat_parse)
    assert out == []
