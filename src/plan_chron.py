"""Harvest SFGate + SF Chronicle food-universe article URLs via their sitemaps.

Same front-door pattern as plan_corpus.py (Eater): both hosts publish open
sitemap indexes with ~3.5k ID-range shards each. We download every shard once
(concurrently), keep only food/restaurant URLs, and grade them hot if the slug
smells like lineage-stating genres (chef moves, closings, openings).

Writes data_chron_urls.json {"all": [...], "hot": [...]} — same shape the
grow loop already understands.

Usage: ./.venv/bin/python src/plan_chron.py
"""
import re, os, sys, json, time, requests
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data_chron_urls.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

HOSTS = ["https://www.sfgate.com", "https://www.sfchronicle.com"]

# food-domain paths: anything under these dirs is already on-topic
FOOD_PATH = re.compile(r"https://www\.(sfgate|sfchronicle)\.com/(food|dining|wine|restaurants|bayarea/food)/", re.I)

# slug words that indicate lineage-stating genres (superset of the Eater list)
HOT = re.compile(r"chef|clos|shut|open|debut|launch|depart|leav|exit|hire|names?[-_]|"
                 r"appoint|helm|kitchen|restaurateur|founder|owner|legend|icon|pioneer|"
                 r"michelin|starred|shut[s]?-doors|last-day|veteran|staple|institution|"
                 r"beloved|landmark|iconic", re.I)

def list_shards(host):
    r = requests.get(host + "/sitemap.xml", headers=UA, timeout=30)
    r.raise_for_status()
    return re.findall(r"<loc>(https://" + host.split("//")[1] + r"/sitemap/[0-9-]+\.xml)</loc>", r.text)

def fetch_shard(url):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            return re.findall(r"<loc>(https://www\.(?:sfgate|sfchronicle)\.com/[^<]+)</loc>", r.text)
        except Exception:
            if attempt == 2:
                return []
            time.sleep(2 * (attempt + 1))

def main():
    all_urls, hot_urls = set(), set()
    for host in HOSTS:
        shards = list_shards(host)
        print(f"{host}: {len(shards)} shards")
        t0 = time.time()
        done = 0
        with ThreadPoolExecutor(max_workers=10) as ex:
            for urls in ex.map(fetch_shard, shards):
                done += 1
                for u in urls:
                    # food sections only — slug keywords alone match sports
                    # headlines ("open", "chef") across every desk
                    if not FOOD_PATH.search(u):
                        continue
                    slug = u.rstrip("/").rsplit("/", 1)[-1].lower()
                    all_urls.add(u)
                    if HOT.search(slug):
                        hot_urls.add(u)
                if done % 500 == 0:
                    print(f"  [{done}/{len(shards)}] {host} {time.time()-t0:.0f}s — all {len(all_urls)}, hot {len(hot_urls)}")
        print(f"{host} done in {time.time()-t0:.0f}s")

    json.dump({"all": sorted(all_urls), "hot": sorted(hot_urls)}, open(OUT, "w"))
    print(f"\nwrote {OUT}: {len(all_urls)} total, {len(hot_urls)} lineage-genre")

if __name__ == "__main__":
    main()
