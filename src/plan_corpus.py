"""Harvest the complete Eater SF article universe via its monthly sitemaps.

The sitemap index lists 59 monthly sitemaps back to 2007. Each holds every
article URL. We filter by slug keywords for the lineage-genre pieces
(closures, chef moves, openings), then the grow loop fetches + extracts.

Usage: ./.venv/bin/python src/plan_corpus.py   # writes data_eater_urls.json
"""
import re, os, sys, json, time, requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data_eater_urls.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# slug words that indicate lineage-stating genres
HOT = re.compile(r"shuffle|clos|chef-|chef-|new-chef|open|departure|leaves-|landed-|exodus|"
                 r"founder|executive-chef|names-|hires|bell|exit|legend|icon|pioneer", re.I)

def main():
    r = requests.get("https://sf.eater.com/sitemaps", headers=UA, timeout=30)
    r.raise_for_status()
    months = re.findall(r'<loc>(https://sf\.eater\.com/sitemaps/entries/[0-9]{4}/[0-9]{2})</loc>', r.text)
    print("monthly sitemaps:", len(months))

    all_urls, hot_urls = set(), set()
    for i, m in enumerate(months):
        try:
            r = requests.get(m, headers=UA, timeout=30)
            r.raise_for_status()
            urls = re.findall(r'<loc>(https://sf\.eater\.com/[^<]+)</loc>', r.text)
            all_urls.update(urls)
            for u in urls:
                slug = u.rstrip("/").split("/")[-1]
                if HOT.search(slug):
                    hot_urls.add(u)
            print(f"  [{i+1}/{len(months)}] {m[-7:]}: {len(urls)} urls (hot total {len(hot_urls)})")
        except Exception as e:
            print(f"  [{i+1}/{len(months)}] {m[-7:]}: {type(e).__name__}")
        time.sleep(0.4)

    json.dump({"all": sorted(all_urls), "hot": sorted(hot_urls)}, open(OUT, "w"))
    print(f"\nwrote {OUT}: {len(all_urls)} total, {len(hot_urls)} lineage-genre")

if __name__ == "__main__":
    main()
