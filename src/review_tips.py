"""Triage the reader-tip inbox (bone-fides-tips).

Tips are queue, not corpus: nothing enters the lineage index until a human
accepts it here and runs the normal ingest discipline on the source
(same extraction + citation gate as a manual scrape run).

Usage:
  python src/review_tips.py list [--status open|resolved|rejected|ingested] [--type ...]
  python src/review_tips.py show <id>
  python src/review_tips.py set <id> <resolved|rejected|ingested> [--note ...]
"""
import argparse, json, os, sys

def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

STATUSES = ("open", "resolved", "rejected", "ingested")

def main(argv=None):
    load_env()
    p = argparse.ArgumentParser(prog="review_tips", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="list tips")
    p_list.add_argument("--status", default="open", choices=STATUSES + ("all",))
    p_list.add_argument("--type", default=None)
    p_show = sub.add_parser("show", help="one tip, full fields")
    p_show.add_argument("id")
    p_set = sub.add_parser("set", help="update a tip's status")
    p_set.add_argument("id")
    p_set.add_argument("status", choices=STATUSES)
    p_set.add_argument("--note", default=None, help="triage note (why)")
    a = p.parse_args(argv)

    from src.es import make_client, TIPS_INDEX
    es = make_client()

    if a.cmd == "list":
        must = []
        if a.status != "all":
            must.append({"term": {"status": a.status}})
        if a.type:
            must.append({"term": {"type": a.type}})
        body = {"size": 50, "sort": [{"created_at": "asc"}],
                "query": {"bool": {"filter": must}} if must else {"match_all": {}}}
        r = es.search(index=TIPS_INDEX, body=body)
        if not r["hits"]["hits"]:
            print(f"no {a.status} tips")
            return
        for h in r["hits"]["hits"]:
            s = h["_source"]
            print(f"{h['_id']}  {s.get('type')}  {s.get('created_at', '')[:10]}")
            if s.get("person"):
                print(f"    person: {s['person']}")
            if s.get("venue"):
                print(f"    venue:  {s['venue']}")
            if s.get("query"):
                print(f"    query:  {s['query']}")
            if s.get("url"):
                print(f"    url:    {s['url']}")
            if s.get("note"):
                print(f"    note:   {s['note']}")
            print()
        print(f"{len(r['hits']['hits'])} tip(s) [{a.status}]")
    elif a.cmd == "show":
        r = es.get(index=TIPS_INDEX, id=a.id)
        print(json.dumps(r["_source"], indent=2, ensure_ascii=False))
    elif a.cmd == "set":
        doc = {"status": a.status}
        if a.note:
            doc["triage_note"] = a.note
        es.update(index=TIPS_INDEX, id=a.id, body={"doc": doc}, refresh=True)
        print(f"{a.id} -> {a.status}")

if __name__ == "__main__":
    main()
