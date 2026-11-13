"""Career timeline: sequence only what the corpus actually dates.

The timeline exists to make a career legible in order. The failure mode it must
never have is inventing that order: only ~12.5% of edges carry a citable year,
so most moves have no position in time. Anything that places an undated move
into the sequence (by article date, by array order, by chain hop) manufactures a
claim the corpus does not support.
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_EXPLORER = os.path.join(_ROOT, "ui", "explorer.html")


def _html():
    return open(_EXPLORER).read()


def test_timeline_functions_exist():
    html = _html()
    for fn in ("buildTimeline", "timelineHTML"):
        assert f"function {fn}(" in html, f"explorer lost {fn}()"


def test_era_order_is_the_shared_vocabulary():
    """The timeline's ordering must match src/eras.ERA_BUCKETS — a bucket the
    server can stamp but the UI cannot order would silently vanish."""
    from src.eras import ERA_BUCKETS
    html = _html()
    m = re.search(r"const ERA_ORDER = \[([^\]]+)\]", html)
    assert m, "ERA_ORDER missing"
    order = [s.strip().strip("'\"") for s in m.group(1).split(",")]
    assert set(order) == set(ERA_BUCKETS), (
        f"ERA_ORDER {sorted(order)} != server vocabulary {sorted(ERA_BUCKETS)}")


def test_undated_moves_are_never_interleaved():
    """buildTimeline must split dated from undated, not merge them.

    The whole honesty claim rests on this split: an undated move placed in the
    sequence would assert a date the article never stated.
    """
    html = _html()
    m = re.search(r"function buildTimeline\(.*?\n\}", html, re.S)
    assert m, "buildTimeline body not found"
    body = m.group(0)
    assert "dated" in body and "undated" in body, (
        "buildTimeline no longer separates dated from undated moves")
    # the partition must be by era membership
    assert "filter(r => r.era)" in body and "filter(r => !r.era)" in body, (
        "buildTimeline no longer partitions on presence of an era")


def test_timeline_needs_at_least_two_dated_moves():
    """One dated move is not a sequence. Falling back to the chain is correct."""
    html = _html()
    m = re.search(r"function buildTimeline\(.*?\n\}", html, re.S)
    assert "dated.length < 2" in m.group(0), (
        "buildTimeline would render a 'timeline' from a single dated move")


def test_undated_group_is_labelled_with_its_count():
    """A reader must see how much of the record is undated, not just that some
    moves exist without a timeline position."""
    html = _html()
    assert "with no stated year" in html, (
        "the undated group lost its explanatory label")


def test_timeline_does_not_reference_an_undefined_here():
    """The bug a browser caught: timelineHTML called `here()` from buildTimeline's
    scope. It parsed, it threw at render time, and no test noticed because the
    JS is inline and untested."""
    html = _html()
    m = re.search(r"function timelineHTML\(.*?\n\}", html, re.S)
    assert m, "timelineHTML body not found"
    body = m.group(0)
    assert "isHere(" in body, "timelineHTML should use its own isHere() helper"
    assert not re.search(r"[^s]\bhere\(", body), (
        "timelineHTML calls bare here(), which is not in its scope")


def test_timeline_payload_carries_era_mentor_and_published_at():
    """The UI can only sequence what the server sends. All three timeline
    fields must travel in lineage() in BOTH twins."""
    for path in (os.path.join(_ROOT, "ui", "server.py"),
                 os.path.join(_ROOT, "vercel-app", "api", "search.py")):
        src = open(path).read()
        m = re.search(r"def lineage\(.*?\n    return edges", src, re.S)
        assert m, f"{path}: lineage() not found"
        body = m.group(0)
        for field in ("era_bucket", "mentor", "published_at"):
            assert f'"{field}"' in body, (
                f"{path}: lineage() does not return {field!r}, so the timeline "
                f"cannot use it")


def test_published_at_is_not_used_as_a_move_date():
    """Article publication date must never order a career.

    A 2019 article about a 2005 tenure sorts wrong if published_at drives the
    sequence. The timeline orders on era_bucket only.
    """
    html = _html()
    m = re.search(r"function buildTimeline\(.*?\n\}", html, re.S)
    assert "published_at" not in m.group(0), (
        "buildTimeline uses published_at to order moves — that is the article "
        "date, not the employment date")
