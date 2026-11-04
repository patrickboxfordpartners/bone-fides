"""Corpus growth, second source: SFGate + SF Chronicle sitemap pool.

Front-door pipeline: harvest their sitemap shards (plan_chron.py) -> fetch
article text via JSON-LD articleBody (fetch_chron.py, works through the
Chronicle paywall) -> free regex pre-pass -> Mistral structured extraction ->
Elasticsearch. Shares the seen-URL ledger with the Eater loop, so SERP-era
sfgate URLs already in the corpus are not reprocessed.

Usage: ./.venv/bin/python src/grow_chron.py [max_articles]   (default 60)
"""
import os, re, sys, time, json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src.cli import load_env
load_env(os.path.join(BASE, ".env"))

import requests
from src import fetch as fetch_mod
from src.fetch_chron import fetch_chron_text
from src.extract import extract_edges
from src.es import make_client, INDEX, ensure_index, index_edges, build_edge_doc

CHRON_PLAN = os.path.join(BASE, "data_chron_urls.json")
SEEN = os.path.join(BASE, "data_seen_urls.json")

# free regex pre-pass — extended with Chronicle/SFGate personnel-change phrasing
ROLE_HINT = re.compile(
    r"\b(chef|cook|culinary|pastry|kitchen|founder|co-founder|owner|restaurateur)\b", re.I)
MOVE_HINT = re.compile(
    r"\b(join(ed|s|ing)?|depart(ed|s|ure)?|leav(e|es|ing)|hired|appoint(ed|s|ment)?|"
    r"took over|taking over|takes over|at the helm|nam(ed|es|ing)|formerly|previously|"
    r"worked|stints?|came from|went on to|now (at|runs|heads)|opened by|founded by|"
    r"from the (chef|team|folks|people) behind|alums?|chef de cuisine|sous chef|"
    r"executive chef|chef-owner|hands? (of|over)|shut(s|ting)?|closing|final (day|night|service))\b", re.I)

def main(max_articles=60):
    seen = set()
    if os.path.exists(SEEN):
        seen = set(json.load(open(SEEN)))
    print(f"{len(seen)} URLs already processed")

    if not os.path.exists(CHRON_PLAN):
        print("no data_chron_urls.json — run src/plan_chron.py first")
        return
    plan = json.load(open(CHRON_PLAN))
    # cascade: lineage-genre slugs first, then the whole food pool (the free
    # pre-pass keeps broad stretches cheap)
    urls = plan.get("hot") or []
    fresh = [u for u in sorted(urls, reverse=True) if u not in seen]
    if not fresh:
        urls = plan.get("all") or []
        fresh = [u for u in sorted(urls, reverse=True) if u not in seen]
        if fresh:
            print(f"hot pool exhausted; widening to all {len(urls)} food URLs")
    batch = fresh[:max_articles] if fresh else []
    if not batch:
        print("fresh URLs remaining: 0 — pool exhausted")
        return
    print(f"plan: {len(fresh)} fresh of {len(urls)} Chronicle/SFGate URLs (newest first)")

    es = make_client()
    ensure_index(es)
    from mistralai.client.sdk import Mistral
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

    def _persist():
        json.dump(sorted(seen), open(SEEN, "w"))

    new_edges = 0
    done = 0
    for u in batch:
        done += 1
        try:
            # JSON-LD front door first; generic regex extractor as fallback
            text, ok = fetch_chron_text(u)
            if not ok:
                text = fetch_mod.fetch_text(u)
            if not text or len(text) < 400:
                print(f"[{done}/{len(batch)}] skip thin: {u[:80]}")
                seen.add(u); _persist(); continue
            if not (ROLE_HINT.search(text) and MOVE_HINT.search(text)):
                print(f"[{done}/{len(batch)}] pre-pass 0: {u[:80]}")
                seen.add(u); _persist(); continue
            for attempt in range(4):
                try:
                    edges = extract_edges(client, text)
                    break
                except Exception as e:
                    is_rate = "429" in str(e) or "rate" in str(e).lower()
                    if not is_rate or attempt == 3:
                        raise
                    wait = 20 * (attempt + 1)
                    print(f"[{done}/{len(batch)}] rate limited, waiting {wait}s...")
                    time.sleep(wait)
        except Exception as e:
            print(f"[{done}/{len(batch)}] fail: {u[:80]} -> {type(e).__name__} {str(e)[:100]}")
            if "429" in str(e) or "rate" in str(e).lower():
                continue  # don't mark rate-limited URLs as seen — retry next run
            seen.add(u); _persist(); continue
        if edges:
            docs = []
            for e in edges:
                e["source_url"] = u
                docs.append(build_edge_doc(e))
            index_edges(es, docs)
            new_edges += len(edges)
            print(f"[{done}/{len(batch)}] +{len(edges)} edges: {u[:80]}")
        else:
            print(f"[{done}/{len(batch)}] 0 edges: {u[:80]}")
        seen.add(u)
        _persist()
        time.sleep(1.0)

    _persist()
    print(f"DONE: {new_edges} new edges from {done} articles")

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
