"""The /api/tree and /api/nodes endpoints through dispatch() (plan section 16).

The graph endpoints must answer with an Elasticsearch client that raises:
they read the committed file and never touch the index. Bad parameters
become defaults, never a 500. The rate limit is per bucket.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
from src import dossier  # noqa: E402


class Down:
    def search(self, **kw):
        raise RuntimeError("index unreachable")


def _ip(n):
    return "t%d" % n


def _q(full):
    """dispatch() takes the path and the query string separately, the way the
    HTTP adapters split them."""
    path, _, query = full.partition("?")
    return path, query


def test_tree_and_nodes_answer_with_a_dead_client():
    for path in ("/api/tree", "/api/nodes"):
        status, headers, body = dossier.dispatch(*_q(path), "api-1", client=lambda: Down())
        assert status == 200, path
    status, _, body = dossier.dispatch("/api/tree", "k=french-laundry", "api-2", client=lambda: Down())
    assert status == 200 and b'"resolved": true' in body
    status, _, body = dossier.dispatch("/api/nodes", "q=quin&kind=kitchen", "api-3", client=lambda: Down())
    assert status == 200 and b"Quince" in body


def test_tree_resolves_slugs_names_and_folded_articles():
    for q in ("french-laundry", "The French Laundry"):
        status, _, body = dossier.dispatch("/api/tree", "k=" + q.replace(" ", "%20"),
                                           "api-4", client=lambda: Down())
        assert b'"resolved": true' in body, q


def test_unknown_kitchen_returns_200_with_suggestions():
    status, _, body = dossier.dispatch(*_q("/api/tree?k=zzzqx"), "", "api-5",
                                       client=lambda: Down())
    assert status == 200 and b'"resolved": false' in body


def test_bad_parameters_become_defaults_never_500():
    cases = ["/api/tree?k=french-laundry&depth=9",
             "/api/tree?k=french-laundry&depth=zero",
             "/api/tree?k=" + "x" * 500,
             "/api/nodes?q=&kind=bogus",
             "/api/nodes?q=qui&limit=99",
             "/api/nodes?q=qui&near=nothing"]
    for i, path in enumerate(cases):
        status, _, body = dossier.dispatch(*_q(path), "api-6-%d" % i, client=lambda: Down())
        assert status == 200, path


def test_cache_control_is_set_on_the_graph_endpoints():
    status, headers, body = dossier.dispatch("/api/tree", "k=french-laundry", "api-7", client=lambda: Down())
    assert "s-maxage=86400" in headers.get("Cache-Control", "")
    status, headers, body = dossier.dispatch("/api/nodes", "q=qui", "api-8", client=lambda: Down())
    assert "s-maxage=86400" in headers.get("Cache-Control", "")


def test_the_rate_limit_is_per_bucket():
    # the nodes bucket: 120 in 60 s
    for i in range(120):
        status, _, _ = dossier.dispatch(*_q("/api/nodes?q=qui"), "limit-ip", client=lambda: Down())
        assert status == 200, i
    status, _, _ = dossier.dispatch("/api/nodes", "q=qui", "limit-ip", client=lambda: Down())
    assert status == 429
    # a different IP is not affected
    status, _, _ = dossier.dispatch("/api/nodes", "q=qui", "limit-other", client=lambda: Down())
    assert status == 200


def test_tree_booking_comes_from_dossier_booking_by_display_name():
    status, _, body = dossier.dispatch(*_q("/api/tree?k=quince"), "", "api-9",
                                       client=lambda: Down())
    assert status == 200
    import json
    t = json.loads(body)
    want = dossier.dossier_booking(t["root"]["name"])
    assert (t["root"]["booking"] or None) == (want or None)
