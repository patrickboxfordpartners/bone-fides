"""Fetch SFGate / SF Chronicle article text via JSON-LD NewsArticle blocks.

Both hosts embed the full article body in <script type="application/ld+json">
even when the rendered page is metered — the machine-readable front door.
Falls back to the generic regex prose extractor when JSON-LD is missing/thin.
"""
import re, json, requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

def _find_article(ld):
    items = ld if isinstance(ld, list) else [ld]
    for it in items:
        if isinstance(it, dict):
            t = it.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(x in ("NewsArticle", "ReportageNewsArticle", "Article", "BlogPosting") for x in types):
                return it
    return None

def fetch_chron_text(url, timeout=20):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    lds = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', r.text, re.S)
    body, headline, date = "", "", ""
    for raw in lds:
        try:
            art = _find_article(json.loads(raw.strip()))
        except Exception:
            continue
        if not art:
            continue
        # keep the block with the most articleBody (headline-only stubs exist)
        ab = art.get("articleBody") or ""
        if len(ab) > len(body):
            body = ab
            headline = art.get("headline") or ""
            date = art.get("datePublished") or ""
    if body and len(body) >= 400:
        text = f"TITLE: {headline}\n\n{body}"
        if date:
            text = f"DATE: {date}\n\n" + text
        return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip(), True
    return None, False
