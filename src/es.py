"""Elasticsearch layer: index mapping, doc builder, client factory, hybrid search."""
import os

from src.roles import role_bucket
from src.eras import era_bucket
from src.hoods import load_hood_maps, hood_for

INDEX = "bone-fides-edges"
TIPS_INDEX = "bone-fides-tips"

def build_tip_doc(tip):
    """Reader-submitted correction/source tip. Never auto-ingested; the tips
    index is a triage inbox for the corpus-growth loop, not the corpus."""
    return {
        "query": tip.get("query"),
        "context": tip.get("context"),
        "person": tip.get("person"),
        "venue": tip.get("venue"),
        "type": tip["type"],
        "url": tip.get("url"),
        "note": tip.get("note"),
        "ip": tip.get("ip"),
        "created_at": tip.get("created_at"),
        "status": "open",
    }

TIPS_SETTINGS = {
    "mappings": {
        "properties": {
            "query": {"type": "keyword"},
            "context": {"type": "keyword"},
            "person": {"type": "keyword"},
            "venue": {"type": "keyword"},
            "type": {"type": "keyword"},
            "url": {"type": "keyword"},
            "note": {"type": "text"},
            "ip": {"type": "keyword", "index": False},
            "created_at": {"type": "date"},
            "status": {"type": "keyword"},
        }
    }
}

_HOOD_MAPS = None

def _hood_stamps(edge, maps=None):
    """Neighborhoods of the venues this edge touches (0-2 keyword values).

    Only SF venues the city file can place get a stamp; non-SF venues and
    unverifiable names stay null (the facet discloses partial coverage).
    """
    m = maps if maps is not None else _get_maps()
    out = []
    for v in (edge.get("from_venue"), edge.get("to_venue")):
        if not v:
            continue
        h = hood_for(v, m)
        if h and h not in out:
            out.append(h)
    return out

def _get_maps():
    global _HOOD_MAPS
    if _HOOD_MAPS is None:
        _HOOD_MAPS = load_hood_maps()
    return _HOOD_MAPS

def build_edge_doc(edge):
    """Flat, citation-bearing doc; text copies feed keyword + semantic search.

    role_bucket / era_bucket / hood stamps are applied at index time so
    /api/search?role=&era=&hood= can filter with term queries — the raw
    role text stays for display."""
    venue_bits = [v for v in (edge.get("from_venue"), edge.get("to_venue")) if v]
    return {
        "person": edge["person"],
        "person_text": edge["person"],
        "from_venue": edge.get("from_venue"),
        "to_venue": edge.get("to_venue"),
        "venue_text": " ".join(venue_bits) if venue_bits else edge.get("role", ""),
        "role": edge.get("role"),
        "role_bucket": role_bucket(edge.get("role")),
        "era_bucket": era_bucket(edge.get("date")),
        "venue_hoods": _hood_stamps(edge),
        "action": edge.get("action"),
        "mentor": edge.get("mentor"),
        "date": edge.get("date"),
        "evidence": edge.get("evidence"),
        "confidence": edge.get("confidence"),
        "source_url": edge["source_url"],
        "source": edge.get("source"),  # source tier: eater | sfgate | sfchronicle
    }

INDEX_SETTINGS = {
    "mappings": {
        "properties": {
            "person": {"type": "keyword"},
            "person_text": {"type": "text"},
            "from_venue": {"type": "keyword"},
            "to_venue": {"type": "keyword"},
            "venue_text": {"type": "text"},
            "role": {"type": "text"},
            "role_bucket": {"type": "keyword"},
            "era_bucket": {"type": "keyword"},
            "venue_hoods": {"type": "keyword"},
            "action": {"type": "keyword"},
            "mentor": {"type": "keyword"},
            "date": {"type": "text"},
            "evidence": {"type": "text"},
            "confidence": {"type": "keyword"},
            "source_url": {"type": "keyword"},
            "source_image": {"type": "keyword", "index": False, "doc_values": False},
            "source": {"type": "keyword"},
            "semantic": {"type": "semantic_text", "inference_id": ".openai-text-embedding-3-small"},
        }
    }
}

def make_client(endpoint=None, api_key=None):
    from elasticsearch import Elasticsearch
    return Elasticsearch(
        endpoint or os.environ["ELASTIC_ENDPOINT"],
        api_key=api_key or os.environ["ELASTIC_API_KEY"],
        request_timeout=30,
    )

def ensure_index(es, index=INDEX):
    if not es.indices.exists(index=index):
        es.indices.create(index=index, mappings=INDEX_SETTINGS["mappings"])

def ensure_tips_index(es):
    if not es.indices.exists(index=TIPS_INDEX):
        es.indices.create(index=TIPS_INDEX, mappings=TIPS_SETTINGS["mappings"])

def index_edges(es, docs, index=INDEX):
    """Bulk-index, retrying through transient timeouts (the semantic_text field
    generates embeddings server-side per doc, which intermittently stalls)."""
    import time
    from elasticsearch.helpers import bulk
    from elastic_transport import ConnectionTimeout
    actions = [{"_index": index, "_source": d} for d in docs]
    for attempt in range(4):
        try:
            bulk(es, actions, request_timeout=120)
            break
        except ConnectionTimeout:
            if attempt == 3:
                raise
            print(f"  index timeout, retrying in {15 * (attempt + 1)}s...")
            time.sleep(15 * (attempt + 1))
    try:
        es.indices.refresh(index=index)
    except Exception:
        pass  # refresh is an optimization; the next refresh will catch up

def find_edges(es, query, index=INDEX, size=20, role=None, era=None, hood=None):
    """Hybrid search: fuzzy keyword on names + sparse_vector on semantic_text field.

    role/era/hood: optional facet filters (src.roles / src.eras vocabularies,
    hood = city analysis_neighborhood label). Applied as post_filter — they
    gate the final RRF hit list without touching ranking, so a filtered
    dossier is exactly the unfiltered dossier with rows removed (this ES
    version rejects sparse_vector nested inside bool). Multiple facets
    compose with AND; era/hood fields are multi-valued so they filter on
    any listed value."""
    body = {
        "size": size,
        "retriever": {
            "rrf": {
                "retrievers": [
                    {"standard": {"query": {
                        "bool": {"should": [
                            {"match": {"person_text": {"query": query, "fuzziness": "AUTO"}}},
                            {"match": {"venue_text": {"query": query, "fuzziness": "AUTO"}}},
                            {"match": {"evidence": {"query": query}}},
                        ]},
                    }}},
                    {"standard": {"query": {"sparse_vector": {"field": "semantic", "query": query}}}},
                ],
                "rank_constant": 20,
                "rank_window_size": max(50, size),
            }
        },
    }
    gates = []
    if role:
        gates.append({"term": {"role_bucket": role}})
    if era:
        gates.append({"term": {"era_bucket": era}})
    if hood:
        gates.append({"term": {"venue_hoods": hood}})
    if len(gates) == 1:
        body["post_filter"] = gates[0]
    elif gates:
        body["post_filter"] = {"bool": {"filter": gates}}
    return es.search(index=index, body=body)["hits"]["hits"]
