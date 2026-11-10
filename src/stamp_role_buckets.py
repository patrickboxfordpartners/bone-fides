"""One-off data run: stamp role_bucket onto every existing edge doc.

Roadmap 4.3 — the &role= facet filters on an index-time keyword field, but
the index predates the stamp. Scroll the index, compute the bucket from
each doc's raw role with src.roles.role_bucket (the same function the twins
use), and bulk-update in place. Idempotent: reruns produce the same stamps.

Usage: PYTHONPATH=. .venv/bin/python src/stamp_role_buckets.py [--dry-run]
"""
import sys

from src.cli import load_env
from src.roles import role_bucket, BUCKETS
from src.es import make_client, INDEX


def main(argv=None):
    load_env()
    dry = "--dry-run" in (argv or sys.argv[1:])
    es = make_client()
    from elasticsearch.helpers import scan
    counts = {b: 0 for b in BUCKETS}
    updated = 0
    scanned = 0
    actions = []
    for hit in scan(es, index=INDEX, query={"query": {"match_all": {}}},
                    source_includes=["role"], size=1000, request_timeout=120):
        scanned += 1
        b = role_bucket(hit["_source"].get("role"))
        counts[b] += 1
        if dry:
            continue
        actions.append({"_op_type": "update", "_index": INDEX,
                        "_id": hit["_id"], "doc": {"role_bucket": b}})
        if len(actions) >= 500:
            _bulk(es, actions)
            updated += len(actions)
            actions = []
    if actions and not dry:
        _bulk(es, actions)
        updated += len(actions)
    print(f"scanned {scanned} docs, updated {updated} role_bucket stamps")
    for b in BUCKETS:
        print(f"  {b}: {counts[b]}")
    if dry:
        print("dry run — nothing written")


def _bulk(es, actions):
    from elasticsearch.helpers import bulk
    bulk(es, actions, request_timeout=120)
    es.indices.refresh(index=INDEX)


if __name__ == "__main__":
    main()
