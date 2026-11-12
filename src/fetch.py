"""Fetch article text from a URL, keeping only readable prose."""
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
STRIP_TAGS = re.compile(r"<(script|style|nav|footer|header|aside|form|noscript)\b[^>]*>.*?</\1>", re.S | re.I)
ALL_TAGS = re.compile(r"<[^>]+>")

def fetch_text(url, timeout=20):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return extract_text_from_html(r.text)

def fetch_article(url, timeout=20):
    """One request -> (text, published_at). Prefer this over fetch_text where
    the caller will index edges: the publication date is free on a response we
    already downloaded, and paying for a second GET just for metadata is waste.
    """
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return extract_text_from_html(r.text), extract_published_at(r.text)

# Publication date, when the page states one. Order matters: an explicit
# article:published_time is the publisher's own claim; datePublished in JSON-LD
# is next; a bare <time datetime> is last because it can carry a modified date.
_PUB_PATTERNS = (
    r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
    r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+itemprop=["\']datePublished["\']',
    r'"datePublished"\s*:\s*"([^"]+)"',
    r'<time[^>]+datetime=["\']([^"\']+)',
)

def extract_published_at(html):
    """ISO-ish publication date from the page, or None.

    A move's date (what the article says happened) and the article's
    publication date are different facts, and conflating them is how
    "published 2019" silently becomes "worked there in 2019". Recording
    published_at separately lets a reader see both.

    Returns the raw matched string, not a parsed datetime: publishers are
    inconsistent and a wrong parse is worse than an honest string. None when
    the page states no date — never guessed from the URL, which carries a date
    for Eater but not for every outlet.
    """
    for pat in _PUB_PATTERNS:
        m = re.search(pat, html, re.S | re.I)
        if m:
            val = _strip_ws(m.group(1))
            if val and len(val) >= 8:
                return val
    return None

def extract_text_from_html(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = _strip_ws(ALL_TAGS.sub(" ", m.group(1))) if m else ""
    body = STRIP_TAGS.sub(" ", html)
    m = re.search(r"<article\b.*?</article>", body, re.S | re.I)
    if m:
        body = m.group(0)
    text = ALL_TAGS.sub(" ", body)
    text = _strip_ws(text)
    if title:
        text = f"TITLE: {title}\n\n{text}"
    return text

def _strip_ws(s):
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", s)).strip()
