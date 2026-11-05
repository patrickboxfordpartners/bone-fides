"""Backfill source image URLs: one fetch per distinct source article, then
update every edge citing that article with the image URL. Idempotent —
re-runs skip articles already stamped."""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.cli import load_env
load_env(os.path.join(os.getcwd(), ".env"))
from src.es import make_client, INDEX
from src.images import fetch_image

CACHE = "data_source_images.json"

def main(limit=None):
    es = make_client()
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            cache = json.load(f)

    # distinct articles + how many edges cite each
    r = es.search(index=INDEX, body={"size": 0, "aggs": {
        "u": {"terms": {"field": "source_url.keyword", "size": 65536}}}})
    buckets = r["aggregations"]["u"]["buckets"]
    todo = [b["key"] for b in buckets if b["key"] not in cache]
    if limit:
        todo = todo[:limit]
    print(f"articles: {len(buckets)} total, {len(todo)} to fetch, {len(cache)} cached")

    hits = 0
    for i, url in enumerate(todo):
        img = fetch_image(url)
        cache[url] = img
        if img:
            hits += 1
        if (i + 1) % 25 == 0:
            with open(CACHE, "w") as f:
                json.dump(cache, f)
            print(f"[{i+1}/{len(todo)}] +{hits} images")
        time.sleep(0.3)  # polite crawl pace
    with open(CACHE, "w") as f:
        json.dump(cache, f)
    print(f"DONE: {hits} images of {len(todo)} fetched ({len(cache)} cached total)")

def stamp(es=None):
    """Push cached image URLs onto every edge doc whose article has one."""
    if not os.path.exists(CACHE):
        print("no cache file")
        return
    with open(CACHE) as f:
        cache = json.load(f)
    stamped = {u: img for u, img in cache.items() if img}
    print(f"{len(stamped)} articles with images")
    if not stamped:
        return
    es = es or make_client()
    from elasticsearch.helpers import scan, bulk
    actions = []
    for h in scan(es, index=INDEX, query={"query": {"terms": {"source_url.keyword": list(stamped.keys())}}},
                  _source=["source_url"]):
        s = h["_source"]
        img = stamped.get(s.get("source_url"))
        if img and s.get("source_image") != img:
            actions.append({"_op_type": "update", "_id": h["_id"],
                            "_index": INDEX, "doc": {"source_image": img}})
    print(f"updating {len(actions)} edge docs")
    for attempt in range(4):
        try:
            bulk(es, actions, request_timeout=120)
            break
        except Exception as e:
            if attempt == 3:
                raise
            print("  bulk timeout, retrying...")
            time.sleep(15)
    try:
        es.indices.refresh(index=INDEX)
    except Exception:
        pass
    print("stamped")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stamp":
        stamp()
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
