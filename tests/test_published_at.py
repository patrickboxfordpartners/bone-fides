"""Publication-date capture: keep the article's date separate from the move's.

The corpus records a move's date (what the article says happened) but until now
had no record of when the ARTICLE was published. Those are different facts, and
conflating them is how "published 2019" silently becomes "worked there in 2019"
— a real accuracy failure the methodology page has to be able to explain.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.fetch import extract_published_at  # noqa: E402
from src.es import build_edge_doc  # noqa: E402


def test_reads_article_published_time_meta():
    html = '<meta property="article:published_time" content="2015-09-23T10:00:00Z">'
    assert extract_published_at(html) == "2015-09-23T10:00:00Z"


def test_reads_meta_when_content_precedes_property():
    """Attribute order varies by publisher; both orders are common in the wild."""
    html = '<meta content="2019-03-25T08:00:00-07:00" property="article:published_time">'
    assert extract_published_at(html) == "2019-03-25T08:00:00-07:00"


def test_reads_json_ld_date_published():
    html = '<script>{"@type":"Article","datePublished":"2017-05-02T12:00:00Z"}</script>'
    assert extract_published_at(html) == "2017-05-02T12:00:00Z"


def test_reads_bare_time_element():
    html = '<time datetime="2014-01-16">January 16, 2014</time>'
    assert extract_published_at(html) == "2014-01-16"


def test_returns_none_when_page_states_no_date():
    """Never guess. A publisher with no date gets no date — not a URL-derived
    one, because only some outlets put a date in the URL path."""
    assert extract_published_at("<html><body>No date anywhere.</body></html>") is None


def test_ignores_too_short_matches():
    """A 4-character 'date' is noise, not a date."""
    html = '<meta property="article:published_time" content="2015">'
    assert extract_published_at(html) is None


def test_build_edge_doc_carries_published_at_separately_from_date():
    """The two dates must not collapse into one field.

    edge.date is the move's date; edge.published_at is the article's. A doc
    that set published_at from date (or vice versa) would make the methodology
    page's promise — that you can tell them apart — false.
    """
    edge = {
        "person": "Alexander Ong", "from_venue": "Betelnut", "to_venue": None,
        "role": "executive chef", "date": "2001-2013",
        "evidence": "Ong ran the kitchen", "confidence": "high",
        "source_url": "https://sf.eater.com/2015/9/23/x",
        "published_at": "2015-09-23T10:00:00Z",
    }
    doc = build_edge_doc(edge)
    assert doc["date"] == "2001-2013"
    assert doc["published_at"] == "2015-09-23T10:00:00Z"


def test_build_edge_doc_allows_absent_published_at():
    """Pre-existing edges carry no publication date. That must be None, not a
    fabricated value."""
    doc = build_edge_doc({
        "person": "X", "from_venue": "A", "to_venue": "B", "role": "chef",
        "evidence": "e", "confidence": "high", "source_url": "https://x.test/1",
    })
    assert doc["published_at"] is None
