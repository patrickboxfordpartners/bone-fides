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
