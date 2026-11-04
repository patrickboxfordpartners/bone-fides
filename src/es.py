"""Elasticsearch layer: index mapping, doc builder, client factory, hybrid search."""
import os

INDEX = "bone-fides-edges"

def build_edge_doc(edge):
    """Flat, citation-bearing doc; text copies feed keyword + semantic search."""
    venue_bits = [v for v in (edge.get("from_venue"), edge.get("to_venue")) if v]
    return {
        "person": edge["person"],
        "person_text": edge["person"],
        "from_venue": edge.get("from_venue"),
        "to_venue": edge.get("to_venue"),
        "venue_text": " ".join(venue_bits) if venue_bits else edge.get("role", ""),
        "role": edge.get("role"),
        "date": edge.get("date"),
        "evidence": edge.get("evidence"),
        "confidence": edge.get("confidence"),
        "source_url": edge["source_url"],
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
            "date": {"type": "text"},
            "evidence": {"type": "text"},
            "confidence": {"type": "keyword"},
            "source_url": {"type": "keyword"},
            "semantic": {"type": "semantic_text"},
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

def index_edges(es, docs, index=INDEX):
    from elasticsearch.helpers import bulk
    actions = [{"_index": index, "_source": d} for d in docs]
    bulk(es, actions)
    es.indices.refresh(index=index)

def find_edges(es, query, index=INDEX, size=20):
    """Hybrid search: fuzzy keyword on names + semantic_text on lineage text."""
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
                    {"semantic": {"field": "semantic", "query": query}},
                ],
                "rank_constant": 20,
            }
        },
    }
    return es.search(index=index, body=body)["hits"]["hits"]
