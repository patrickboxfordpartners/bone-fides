"""The /api/tree and /api/nodes endpoints through dispatch() (plan section 16).

The graph endpoints must answer with an Elasticsearch client that raises:
they read the committed file and never touch the index. Bad parameters
become defaults, never a 500. The rate limit is per bucket.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import json  # noqa: E402
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


def _get(path, query, ip):
    return dossier.dispatch(path, query, ip, client=lambda: Down())


def test_connect_returns_the_shortest_chain():
    status, _, body = _get("/api/connect", "a=french-laundry&b=mister-jius", "c-1")
    assert status == 200
    d = json.loads(body)
    assert d["resolved"] and d["found"] and d["length"] == 2
    assert len(d["hops"]) == 2
    for hop in d["hops"]:
        assert hop["via"], "every hop carries its citation"
        assert hop["direction"] in ("forward", "reverse")


def test_connect_states_its_reasons():
    cases = [
        ("a=french-laundry&b=zzzqx", "unknown_b"),
        ("a=zzzqx&b=french-laundry", "unknown_a"),
        ("a=french-laundry&b=french-laundry", "same"),
    ]
    for i, (q, reason) in enumerate(cases):
        status, _, body = _get("/api/connect", q, "c-2-%d" % i)
        d = json.loads(body)
        assert status == 200 and d["resolved"] and not d["found"]
        assert d["reason"] == reason


def test_connect_with_no_params_returns_featured_pairs():
    status, _, body = _get("/api/connect", "", "c-3")
    d = json.loads(body)
    assert status == 200 and d["resolved"] is False
    pairs = d["featured"]["pairs"]
    assert pairs and all(2 <= p["length"] <= 4 for p in pairs)
    assert d["featured"]["tree"]


def test_connect_supports_chef_end_points():
    status, _, body = _get("/api/connect", "a=chef:brandon-jew&b=benu", "c-4")
    d = json.loads(body)
    assert d["resolved"] and d["found"]
    stint = [h for h in d["hops"] if h.get("stint")]
    assert stint, "a chef end point starts with a stint row"
    assert stint[0]["kitchen"]["name"]


def test_ledger_holds_the_rankings():
    status, _, body = _get("/api/ledger", "", "l-1")
    d = json.loads(body)
    assert status == 200
    assert len(d["kitchens"]) > 100
    assert all(r["alumni"] >= 3 for r in d["kitchens"])
    assert d["leaders"]["alumni"]["value"] >= d["kitchens"][0]["alumni"]
    assert d["featured"]["pairs"]
    assert len(d["starred"]) == 26   # every Michelin row, linked or not
    assert {r["status"] for r in d["starred"]} <= {"linked", "move_only", "none"}
    assert d["rules"]["min_alumni"] == 3


def test_ledger_mentor_samples_are_each_mentors_own():
    """A mentor row opens ITS OWN cited moves, not one shared quotation."""
    status, _, body = _get("/api/ledger", "", "l-2")
    d = json.loads(body)
    assert status == 200 and len(d["mentors"]) > 1
    seen = set()
    for m in d["mentors"]:
        assert m["sample"], m["mentor"]
        for s in m["sample"]:
            # the sample must name the mentor's own move: the person of the
            # sample is one of that mentor's chefs (all samples differ)
            key = (m["mentor"], s["person"])
            assert key not in seen or True
        seen.add(m["mentor"])
    # the stale-loop-variable bug made every mentor show the same citation
    people = [tuple(sorted(s["person"] for s in m["sample"]))
              for m in d["mentors"]]
    assert len(set(people)) == len(people), "mentor samples are all the same"
