"""Corpus growth loop: Bright Data SERP discovery -> fetch -> Mistral extract -> index.

Queries target extraction-friendly food journalism: chef-shuffle roundups,
closures, openings, chef-profiles — the genres that state lineage outright.

Usage: ./.venv/bin/python src/grow_corpus.py [max_articles]
       (default 60; each article = 1 SERP discovery batch + 1 Mistral call)
"""
import os, re, sys, time, json, html, urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src.cli import load_env
load_env(os.path.join(BASE, ".env"))

# Bright Data creds may live in bone-fides/.env or the boxford clone's .env
def _bd_creds():
    for path in (os.path.join(BASE, ".env"),
                 os.path.expanduser("~/clones/boxford-crm-brightdata/.env")):
        if not os.path.exists(path):
            continue
        creds = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("BRIGHTDATA_"):
                    k, _, v = line.partition("=")
                    creds[k] = v.strip().strip('"').strip("'")
        # zone may be set while the key is still pending paste
        if creds.get("BRIGHTDATA_API_KEY") and creds.get("BRIGHTDATA_SERP_ZONE"):
            return creds
    return None

CREDS = _bd_creds()

import requests
from src import fetch as fetch_mod
from src.extract import extract_edges, parse_extraction
from src.es import make_client, INDEX, ensure_index, index_edges, build_edge_doc

QUERIES = [
    "site:sf.eater.com chef shuffle san francisco",
    "site:sf.eater.com san francisco restaurant closed chef",
    "site:sf.eater.com new chef restaurant san francisco",
    "site:sf.eater.com chef departs restaurant san francisco",
    "site:sfgate.com san francisco restaurant chef new executive chef",
    "site:sf.eater.com san francisco restaurant opening chef formerly",
    "site:sf.eater.com chef profile san francisco restaurant",
    "site:sf.eater.com Michelin star new chef san francisco",
    "site:sf.eater.com san francisco iconic restaurant closing chef",
    "site:sfgate.com san francisco beloved restaurant closes chef",
]

EATER_PLAN = os.path.join(BASE, "data_eater_urls.json")
SEEN = os.path.join(BASE, "data_seen_urls.json")

# free regex pre-pass: an edge needs a person (chef/owner/founder) and a move
# verb; articles with neither almost never yield one, so skip them before
# spending a Mistral call
ROLE_HINT = re.compile(
    r"\b(chef|cook|culinary|pastry|kitchen|founder|co-founder|owner|restaurateur)\b", re.I)
MOVE_HINT = re.compile(
    r"\b(join(ed|s|ing)?|depart(ed|s|ure)?|leav(e|es|ing)|hired|appoint(ed|s|ment)?|"
    r"took over|at the helm|formerly|previously|worked|stints?|came from|went on to|"
    r"now (at|runs|heads)|opened by|founded by|from the (chef|team|folks|people) behind|"
    r"alums?|chef de cuisine|sous chef|executive chef|chef-owner|hands? (of|over))\b", re.I)

def discover(serp_fn, queries, per_query=20):
    """SERP queries -> candidate article URLs (already filtered by site:)."""
    urls = []
    for q in queries:
        try:
            res = serp_fn(q, num=per_query)
        except Exception as e:
            print(f"  serp fail [{q[:50]}]: {type(e).__name__} {str(e)[:120]}")
            continue
        for r in res:
            u = r["url"].split("#")[0]
            if re.match(r"https?://(www\.)?(sf\.)?eater\.com/|sfgate\.com/", u):
                urls.append(u)
        time.sleep(0.6)
    return sorted(set(urls))

def main(max_articles=60):
    import json as _json
    import urllib.request, urllib.parse

    seen = set()
    if os.path.exists(SEEN):
        seen = set(_json.load(open(SEEN)))
    print(f"{len(seen)} URLs already processed")

    es = make_client()
    ensure_index(es)
    from mistralai.client.sdk import Mistral
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

    # primary source: the sitemap-harvested Eater lineage-genre list (free).
    # cascade: "hot" lineage-genre slugs first, then the full "all" list (the
    # free regex pre-pass keeps broad stretches cheap), SERP last (credits)
    urls = []
    if os.path.exists(EATER_PLAN):
        plan = _json.load(open(EATER_PLAN))
        urls = plan.get("hot") or []
        fresh = [u for u in sorted(urls, reverse=True) if u not in seen]
        if not fresh:
            urls = plan.get("all") or []
            fresh = [u for u in sorted(urls, reverse=True) if u not in seen]
            if fresh:
                print(f"hot pool exhausted; widening to all {len(urls)} sitemap URLs")
        urls = [u for u in fresh][:max_articles] if fresh else sorted(urls, reverse=True)
        if fresh:
            print(f"sitemap plan: {len(fresh)} fresh of {len(urls)} lineage-genre Eater URLs (newest first)")
    if not urls:  # fallback: Bright Data SERP discovery
        if not CREDS:
            print("no sitemap plan and no Bright Data creds — nothing to do")
            return
        print("falling back to SERP discovery")

        def serp_fn(query, num):
            google = ("https://www.google.com/search?q=" + urllib.parse.quote(query)
                      + f"&hl=en&gl=us&num={num}&brd_json=1")
            req = urllib.request.Request("https://api.brightdata.com/request",
                data=_json.dumps({"zone": CREDS["BRIGHTDATA_SERP_ZONE"], "url": google,
                                  "format": "raw"}).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + CREDS["BRIGHTDATA_API_KEY"]})
            with urllib.request.urlopen(req, timeout=45) as r:
                data = _json.loads(r.read().decode("utf-8", "replace"))
            if isinstance(data, dict) and isinstance(data.get("body"), str):
                data = _json.loads(data["body"])
            out = []
            for o in (data.get("organic") or []):
                link = o.get("link") or o.get("url") or ""
                if not link or "google.com/goto" in link:
                    continue
                out.append({"url": link, "title": o.get("title") or ""})
            return out

        urls = discover(serp_fn, QUERIES)

    fresh = [u for u in urls if u not in seen][:max_articles]
    print(f"{len(fresh)} fresh of {len(urls)} — processing up to {max_articles}")

    new_edges = 0
    done = 0
    for u in fresh:
        done += 1
        try:
            text = fetch_mod.fetch_text(u)
            if not text or len(text) < 400:
                print(f"[{done}/{len(fresh)}] skip thin: {u[:80]}")
                seen.add(u); continue
            if not (ROLE_HINT.search(text) and MOVE_HINT.search(text)):
                print(f"[{done}/{len(fresh)}] pre-pass 0: {u[:80]}")
                seen.add(u); continue
            for attempt in range(4):
                try:
                    edges = extract_edges(client, text)
                    break
                except Exception as e:
                    is_rate = "429" in str(e) or "rate" in str(e).lower()
                    if not is_rate or attempt == 3:
                        raise
                    wait = 20 * (attempt + 1)
                    print(f"[{done}/{len(fresh)}] rate limited, waiting {wait}s...")
                    time.sleep(wait)
        except Exception as e:
            print(f"[{done}/{len(fresh)}] fail: {u[:80]} -> {type(e).__name__} {str(e)[:100]}")
            if "429" in str(e) or "rate" in str(e).lower():
                continue  # don't mark rate-limited URLs as seen — retry next run
            seen.add(u); continue
        if edges:
            docs = []
            for e in edges:
                e["source_url"] = u
                docs.append(build_edge_doc(e))
            index_edges(es, docs)
            new_edges += len(edges)
            print(f"[{done}/{len(fresh)}] +{len(edges)} edges: {u[:80]}")
        else:
            print(f"[{done}/{len(fresh)}] 0 edges: {u[:80]}")
        seen.add(u)
        _json.dump(sorted(seen), open(SEEN, "w"))
        time.sleep(1.0)

    print(f"DONE: {new_edges} new edges from {done} articles")

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
