"""Image fetcher: pull each source article's lead photo from its JSON-LD / OG meta.

Only images embedded in the article the edge was cited from — never scraped
from elsewhere. The image URL lands in the edge doc with the article it came
from, so every photo keeps its citation.
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

def _pick(urls):
    """First usable http(s) image URL, rejecting placeholders (site-default
    art, spacers, logos) that would render as noise in the dossier."""
    for u in urls:
        if not u or not u.startswith("http"):
            continue
        lu = u.lower()
        if lu.endswith((".svg", ".gif")):
            continue
        if any(p in lu for p in ("default", "placeholder", "logo", "spacer",
                                 "og-default", "fallback", "eater-default")):
            continue
        return u
    return None

def fetch_image(url, timeout=20):
    """Return the article's lead image URL, or None."""
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        if r.status_code != 200:
            return None
    except Exception:
        return None
    html = r.text
    # 1. JSON-LD ImageObject / image lists (same front door as the text fetcher)
    urls = []
    for raw in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            art = _find_article(json.loads(raw.strip()))
        except Exception:
            continue
        if not art:
            continue
        img = art.get("image")
        if isinstance(img, dict):
            img = img.get("url")
        if isinstance(img, list):
            urls.extend(x.get("url") if isinstance(x, dict) else x for x in img)
        elif img:
            urls.append(img)
    # 2. OG meta as fallback
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if m:
        urls.append(m.group(1))
    m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.I)
    if m:
        urls.append(m.group(1))
    return _pick(urls)
