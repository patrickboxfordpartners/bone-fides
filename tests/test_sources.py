import textwrap
from src.sources import load_sources

def test_loads_urls_and_notes_from_reading_list(tmp_path):
    md = textwrap.dedent("""
    | # | Source | What it gives us |
    |---|--------|------------------|
    | 1 | https://sf.eater.com/2015/9/23/9389543/say-bye-to-betelnut-closing-after-20-years-in-cow-hollow | The closure. Names exec chef Alexander Ong's exit. |
    | 2 | https://example.com/article | A note here |
    """)
    p = tmp_path / "READING-LIST.md"
    p.write_text(md)
    sources = load_sources(p)
    assert len(sources) == 2
    assert sources[0]["url"].startswith("https://sf.eater.com")
    assert sources[0]["note"].startswith("The closure")
    assert "eater.com" in sources[0]["source_name"]

def test_skips_header_and_separator_rows(tmp_path):
    md = textwrap.dedent("""
    | Source | What it gives us |
    |---|---|
    """)
    p = tmp_path / "READING-LIST.md"
    p.write_text(md)
    assert load_sources(p) == []
