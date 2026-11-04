"""Source list: reading-list.md -> fetchable article URLs."""
import re
from pathlib import Path

URL_RE = re.compile(r"https?://[^\s|)]+")

def load_sources(path="READING-LIST.md"):
    """Extract article URLs + their 'what it gives us' descriptions from the reading list.

    Returns list of dicts: {url, source_name, note} — ordered as listed.
    """
    text = Path(path).read_text()
    sources = []
    for line in text.splitlines():
        if not line.strip().startswith("|") or "Source" in line.split("|")[1]:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[1]:
            continue
        m = URL_RE.search(cells[1])
        if not m:
            continue
        url = m.group(0).rstrip(".,;")
        sources.append({
            "url": url,
            "source_name": _short_name(url),
            "note": cells[2],
        })
    return sources

def _short_name(url):
    m = re.search(r"https?://([^/]+)", url)
    return m.group(1) if m else url
