"""Bone Fides CLI: ingest the reading list, query lineage."""
import argparse, json, sys, os

def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

def main(argv=None):
    load_env()
    p = argparse.ArgumentParser(prog="bone-fides")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_ing = sub.add_parser("ingest", help="run the reading list through Mistral -> ES")
    p_ing.add_argument("--url", action="append", help="specific URL(s) instead of the reading list")
    p_q = sub.add_parser("ask", help="query the lineage index")
    p_q.add_argument("query")
    a = p.parse_args(argv)

    from src.es import make_client, ensure_index, index_edges, find_edges, INDEX
    if a.cmd == "ingest":
        from mistralai.client.sdk import Mistral
        from src.pipeline import run_pipeline
        es = make_client()
        ensure_index(es)
        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        urls = a.url or None
        edges = run_pipeline(urls=urls, mistral_client=client)
        docs = [build_doc(e) for e in edges]
        index_edges(es, docs)
        print(f"ingested {len(docs)} edges from {len(urls) if urls else 'the reading list'}")
        for d in docs:
            print(f"  {d['person']}: {d['from_venue']} -> {d['to_venue']} ({d['role']}) [{d['source_url']}]")
    else:
        es = make_client()
        hits = find_edges(es, a.query, index=INDEX)
        if not hits:
            print("no lineage found")
            return
        for h in hits:
            s = h["_source"]
            print(f"{s['person']} ({s.get('role','')}): {s.get('from_venue')} -> {s.get('to_venue')}")
            print(f"   evidence: {s.get('evidence','')}")
            print(f"   source: {s.get('source_url')}")
            print()

def build_doc(e):
    from src.es import build_edge_doc
    return build_edge_doc(e)

if __name__ == "__main__":
    main()
