"""Run the fetch -> extract loop over the reading list, collecting edges."""
from src.sources import load_sources
from src import fetch as fetch_mod
from src.extract import extract_edges

def run_pipeline(urls=None, fetch=None, extract=None, reading_list="READING-LIST.md",
                 mistral_client=None, model="mistral-large-latest", fetch_batch=False):
    """Fetch each source, extract edges, tag every edge with source_url.

    fetch: url -> text (injected; default src.fetch.fetch_text)
    extract: article_text -> list of edge dicts (injected; default Mistral call)
    fetch_batch: fetch serially (True) or concurrently (default False => threads)
    """
    if fetch is None:
        fetch = fetch_mod.fetch_text
    if extract is None:
        def extract(text):
            return extract_edges(mistral_client, text, model=model)

    if urls is None:
        urls = [s["url"] for s in load_sources(reading_list)]

    all_edges = []
    for url in urls:
        try:
            text = fetch(url)
            raw = extract(text)
        except Exception:
            continue
        if isinstance(raw, dict):        # raw model output -> validate
            from src.extract import parse_extraction
            edges = parse_extraction(raw)
        elif isinstance(raw, list):
            edges = raw
        else:
            continue
        for e in edges:
            if isinstance(e, dict):
                e["source_url"] = url
                all_edges.append(e)
    return all_edges
