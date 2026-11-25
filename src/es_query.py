"""Elasticsearch query layer shared by the pipeline and the web API.

Stdlib plus the elasticsearch client only: build.sh ships this file into the
Vercel function bundle (vercel-app/api/_lib/), which has no other src/ modules.
"""
import os

INDEX = "bone-fides-edges"

TIPS_INDEX = "bone-fides-tips"

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

def make_client(endpoint=None, api_key=None):
    from elasticsearch import Elasticsearch
    return Elasticsearch(
        endpoint or os.environ["ELASTIC_ENDPOINT"],
        api_key=api_key or os.environ["ELASTIC_API_KEY"],
        request_timeout=30,
    )

def ensure_tips_index(es):
    if not es.indices.exists(index=TIPS_INDEX):
        es.indices.create(index=TIPS_INDEX, mappings=TIPS_SETTINGS["mappings"])

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
