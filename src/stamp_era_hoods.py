"""One-off data run: stamp era_bucket + venue_hoods onto every edge doc.

Roadmap 4.4 — the &era= and &hood= facets filter on index-time stamps the
same way &role= does (4.3), but the index predates the stamps. Scroll the
index, compute stamps with src.eras.era_bucket / src.hoods.hood_for (the
same functions the twins use via build_edge_doc), and bulk-update in
place. Idempotent: reruns produce the same stamps.

Usage: PYTHONPATH=. .venv/bin/python src/stamp_era_hoods.py [--dry-run]
"""
import sys

from src.cli import load_env
from src.es import make_client, INDEX, build_edge_doc

def main(argv=None):
    load_env()
    dry = "--dry-run" in (argv or sys.argv[1:])
    es = make_client()
    from elasticsearch.helpers import scan
    era_counts = {}
    hood_counts = {}
    updated = 0
    scanned = 0
    actions = []
    for hit in scan(es, index=INDEX, query={"query": {"match_all": {}}},
                    source_includes=["date", "from_venue", "to_venue"],
                    size=1000, request_timeout=120):
        scanned += 1
        s = hit["_source"]
        doc = build_edge_doc({
            "person": "",
            "source_url": "",
            "date": s.get("date"),
            "from_venue": s.get("from_venue"),
            "to_venue": s.get("to_venue"),
        })
        patch = {"era_bucket": doc["era_bucket"],
                 "venue_hoods": doc["venue_hoods"]}
        era_counts[patch["era_bucket"]] = era_counts.get(patch["era_bucket"], 0) + 1
        for h in patch["venue_hoods"]:
            hood_counts[h] = hood_counts.get(h, 0) + 1
        if dry:
            continue
        actions.append({"_op_type": "update", "_index": INDEX,
                        "_id": hit["_id"], "doc": patch})
        if len(actions) >= 500:
            _bulk(es, actions)
            updated += len(actions)
            actions = []
    if actions and not dry:
        _bulk(es, actions)
        updated += len(actions)
    print(f"scanned {scanned} docs, updated {updated} era/hood stamps")
    print("era distribution:")
    for e, n in sorted((era_counts.items()), key=lambda kv: -(kv[1] or 0)):
        print(f"  {n:5d}  {e}")
    print("hood distribution (top 20):")
    for h, n in sorted(hood_counts.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {n:5d}  {h}")

def _bulk(es, actions):
    from elasticsearch.helpers import bulk
    bulk(es, actions, request_timeout=120)
    es.indices.refresh(index=INDEX)

if __name__ == "__main__":
    main()
