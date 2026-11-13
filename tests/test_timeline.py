"""Executable tests for the career timeline.

Greptile's finding, and it was right: the previous version of this file asserted
on source TEXT. Finding `dated.length < 2` in the source does not prove one dated
move returns null, and finding two `filter` calls does not prove undated moves
stay separate. A broken split, a broken fallback, or a broken render all passed.

So these tests EXTRACT the real functions from ui/explorer.html and execute them
in a JavaScript runtime (bun, falling back to deno). What runs in the test is the
same code the browser runs.

If neither runtime is present the behavioural tests skip rather than fail — but
the source-shape checks below still run, and CI should have bun.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_EXPLORER = os.path.join(_ROOT, "ui", "explorer.html")


def _html():
    return open(_EXPLORER).read()


def _runtime():
    """A JS runtime that can run a file, or None."""
    for name, args in (("bun", ["run"]), ("deno", ["run", "--quiet"]),
                       ("node", [])):
        path = shutil.which(name)
        if path:
            return [path] + args
    return None


_RUNTIME = _runtime()

# The functions under test, plus the minimal helpers they call. Extracted from
# the explorer so the test executes the shipped code, not a reimplementation.
_WANTED = ("buildTimeline", "timelineHTML", "looseKey", "sameLoose", "esc")


def _extract_js():
    """Grab the wanted function declarations out of the inline script."""
    html = _html()
    script = re.search(r"<script>\n(.*?)\n</script>", html, re.S)
    assert script, "inline script not found in explorer.html"
    src = script.group(1)
    chunks = []
    for name in _WANTED:
        m = re.search(rf"function {name}\([^)]*\)\{{.*?\n\}}\n", src, re.S)
        if not m:
            m = re.search(rf"const {name} = [^\n]+\n", src)
        assert m, f"could not extract {name}() from explorer.html"
        chunks.append(m.group(0))
    era = re.search(r"const ERA_ORDER = \[[^\]]+\];\n", src)
    assert era, "ERA_ORDER not found"
    return era.group(0) + "\n" + "\n".join(chunks)


def _run_js(body):
    """Run `body` after the extracted functions; return parsed stdout JSON."""
    rt = _RUNTIME
    if not rt:
        pytest.skip("no JS runtime (bun/deno) available")
    prelude = _extract_js()
    script = prelude + "\n" + body
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(script)
        path = f.name
    try:
        out = subprocess.run(rt + [path], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(path)
    assert out.returncode == 0, f"JS failed:\n{out.stderr[:1200]}"
    line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    return json.loads(line)


def _edge(person="A", frm="X", to="Y", era=None, role="chef",
          mentor=None, date=None, url="u1"):
    return {"person": person, "from_venue": frm, "to_venue": to,
            "era_bucket": era, "role": role, "mentor": mentor,
            "date": date, "source_url": url}


# ── behavioural: buildTimeline ─────────────────────────────────────────────

def test_zero_edges_returns_null():
    assert _run_js("console.log(JSON.stringify(buildTimeline([], 'X')));") is None


def test_one_dated_move_is_not_a_timeline():
    """One dated move is not a sequence. The chain is the right render."""
    edges = [_edge(era="2010s")]
    got = _run_js(
        f"console.log(JSON.stringify(buildTimeline({json.dumps(edges)}, 'X')));")
    assert got is None, "a single dated move must not produce a timeline"


def test_two_dated_moves_produce_a_timeline():
    edges = [_edge(era="2010s"), _edge(frm="Y", to="Z", era="2020s", url="u2")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify(t && {{d:t.dated.length,u:t.undated.length}}));")
    assert got == {"d": 2, "u": 0}


def test_dated_moves_sort_by_era():
    edges = [_edge(era="2020s", url="u1"),
             _edge(frm="Y", to="Z", era="1990s", url="u2"),
             _edge(frm="Z", to="W", era="2000s", url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify(t.dated.map(r=>r.era)));")
    assert got == ["1990s", "2000s", "2020s"]


def test_undated_moves_are_kept_separate_never_interleaved():
    """The whole honesty claim: undated moves get no position in the sequence."""
    edges = [_edge(era="2010s", url="u1"),
             _edge(frm="Y", to="Z", era="2020s", url="u2"),
             _edge(frm="Q", to="R", era=None, url="u3"),
             _edge(frm="R", to="S", era=None, url="u4")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify({{d:t.dated.length,u:t.undated.length,"
        f"eras:t.dated.map(r=>r.era),uHasEra:t.undated.some(r=>r.era)}}));")
    assert got["d"] == 2 and got["u"] == 2
    assert got["uHasEra"] is False, "an undated row must not carry an era"
    assert all(e in ("2010s", "2020s") for e in got["eras"])


def test_unknown_era_value_is_treated_as_undated():
    """A bucket the UI cannot order must not enter the sequence."""
    edges = [_edge(era="2010s", url="u1"),
             _edge(frm="Y", to="Z", era="2020s", url="u2"),
             _edge(frm="Q", to="R", era="1899s", url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify({{d:t.dated.length,u:t.undated.length}}));")
    assert got == {"d": 2, "u": 1}, "an unrecognized era bucket must go undated"


def test_same_move_cited_twice_renders_once():
    """A move reported by several articles is ONE move.

    Mourad Lahlou's Aziza->Mourad is cited by three sources; rendering per-edge
    would show the same move three times and inflate a career.
    """
    edges = [_edge(era="2010s", url="u1"),
             _edge(era="2010s", url="u2"),   # same move, second citation
             _edge(frm="Y", to="Z", era="2020s", url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify({{d:t.dated.length}}));")
    assert got["d"] == 2, "duplicate citations of one move must collapse to one row"


def test_role_wording_difference_does_not_split_a_move():
    """The corpus words one move differently across articles.

    Lahlou's Aziza->Mourad appears as 'chef' in one source and 'chef and
    restaurateur' in another. Role is an attribute of the move, not part of its
    identity — keying on it split one move into two rows.
    """
    edges = [_edge(era="2010s", role="chef", url="u1"),
             _edge(era="2010s", role="chef and restaurateur", url="u2"),
             _edge(frm="Y", to="Z", era="2020s", url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify({{d:t.dated.length}}));")
    assert got["d"] == 2, (
        "one move worded two ways must still be one move, not two rows")


def test_different_endpoints_are_different_moves():
    """The inverse guard: dedupe must not over-collapse.

    Two genuinely different moves by the same person must stay two rows.
    """
    edges = [_edge(frm="A", to="B", era="2010s", url="u1"),
             _edge(frm="B", to="C", era="2020s", url="u2"),
             _edge(frm="A", to="C", era="2020s", url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify({{d:t.dated.length}}));")
    assert got["d"] == 3, "distinct venue pairs must remain distinct moves"


def test_same_route_in_two_eras_is_two_events():
    """A chef can be promoted twice at one kitchen, or return years later.

    Collapsing on venue pair alone would drop a real, separately-dated event.
    """
    edges = [_edge(frm="A", to="B", era="2000s", url="u1"),
             _edge(frm="A", to="B", era="2020s", url="u2"),
             _edge(frm="B", to="C", era="2010s", url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify(t.dated.map(r=>r.era)));")
    assert got == ["2000s", "2010s", "2020s"], (
        "the same route in two eras must yield two rows, not one")


def test_merging_citations_keeps_mentor_from_a_different_source():
    """Taking one whole citation discards the other's detail.

    A dated citation and a mentor-naming citation describe the same move; the
    row must carry both, not whichever one scored higher.
    """
    edges = [_edge(era="2010s", mentor=None, url="u1"),
             _edge(era=None, mentor="Bocuse", url="u2"),
             _edge(frm="Y", to="Z", era="2020s", url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify(t.dated.map(r=>({{era:r.era,m:r.e.mentor}}))));")
    assert got[0]["m"] == "Bocuse", (
        "the mentor from the undated citation must survive the merge")
    assert got[0]["era"] == "2010s", "the dated citation must supply the era"


def test_undated_heading_id_is_unique_per_card():
    """A dossier shows several chef cards; a fixed id makes later lists take
    their spoken label from the first chef's heading."""
    edges = [_edge(era="2010s", url="u1"),
             _edge(frm="Y", to="Z", era="2020s", url="u2"),
             _edge(frm="Q", to="R", era=None, url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify([timelineHTML(t,'X',{_CHIP},0),"
        f"timelineHTML(t,'X',{_CHIP},1)]));")
    assert 'id="tl-und-0"' in got[0] and 'id="tl-und-1"' in got[1], (
        "each card's undated heading needs its own id")


def test_direction_is_announced_not_only_drawn():
    """aria-hidden on the arrow removes the only direction cue. Screen-reader
    users must still hear that the move goes from one venue to another."""
    edges = [_edge(era="2010s", url="u1"),
             _edge(frm="Y", to="Z", era="2020s", url="u2"),
             _edge(frm="Q", to="R", era=None, url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify(timelineHTML(t,'X',{_CHIP})));")
    assert "sr-only" in got and "moved to" in got, (
        "the arrow is aria-hidden, so direction needs a screen-reader phrase")


def test_deduped_row_keeps_richer_citation():
    """When two citations differ in detail, the merged row keeps the fuller one
    so a mentor or era is not lost to ordering luck."""
    edges = [_edge(era="2010s", url="u1"),
             _edge(era="2010s", mentor="Bocuse", url="u2"),
             _edge(frm="Y", to="Z", era="2020s", url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify(t.dated.map(r=>r.e.mentor)));")
    assert "Bocuse" in got, "the citation carrying a mentor must win the merge"


def test_moves_with_no_venue_at_all_are_excluded():
    edges = [{"person": "A", "from_venue": None, "to_venue": None,
              "era_bucket": "2010s", "source_url": "u1"}]
    assert _run_js(
        f"console.log(JSON.stringify(buildTimeline({json.dumps(edges)},'X')));"
    ) is None


# ── behavioural: timelineHTML ─────────────────────────────────────────────

_CHIP = "v => '<b>'+v+'</b>'"


def test_render_marks_the_queried_venue_and_labels_undated():
    edges = [_edge(era="2010s", url="u1"),
             _edge(frm="Y", to="Z", era="2020s", url="u2"),
             _edge(frm="Q", to="R", era=None, url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify(timelineHTML(t,'X',{_CHIP})));")
    assert "Career timeline" in got
    assert "1 move with no stated year" in got
    assert "role=\"listitem\"" in got
    assert "tldot here" in got, "the queried venue's dot must be marked"


def test_render_shows_mentor_on_both_dated_and_undated_rows():
    """A mentor fact must not disappear because the move has no year."""
    edges = [_edge(era="2010s", mentor="Bocuse", url="u1"),
             _edge(frm="Y", to="Z", era="2020s", url="u2"),
             _edge(frm="Q", to="R", era=None, mentor="Troisgros", url="u3")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify(timelineHTML(t,'X',{_CHIP})));")
    assert "under Bocuse" in got, "dated row lost its mentor"
    assert "under Troisgros" in got, "undated row lost its mentor"


def test_render_does_not_call_bare_here():
    """The bug a browser caught: timelineHTML called `here()` from buildTimeline's
    scope, which threw at render time. Executing the render proves it is gone."""
    edges = [_edge(era="2010s", url="u1"),
             _edge(frm="Y", to="Z", era="2020s", url="u2")]
    got = _run_js(
        f"const t=buildTimeline({json.dumps(edges)},'X');"
        f"console.log(JSON.stringify(timelineHTML(t,'X',{_CHIP}).length>0));")
    assert got is True, "timelineHTML must render without a ReferenceError"


# ── source-shape (cheap guards, run without a JS runtime) ──────────────────

def test_timeline_functions_exist():
    html = _html()
    for fn in ("buildTimeline", "timelineHTML"):
        assert f"function {fn}(" in html, f"explorer lost {fn}()"


def test_era_order_is_the_shared_vocabulary():
    from src.eras import ERA_BUCKETS
    m = re.search(r"const ERA_ORDER = \[([^\]]+)\]", _html())
    assert m, "ERA_ORDER missing"
    order = [s.strip().strip("'\"") for s in m.group(1).split(",")]
    assert set(order) == set(ERA_BUCKETS), (
        f"ERA_ORDER {sorted(order)} != server vocabulary {sorted(ERA_BUCKETS)}")


def test_timeline_payload_carries_era_mentor_and_published_at():
    """The UI can only sequence what the server sends — in BOTH twins."""
    for path in (os.path.join(_ROOT, "ui", "server.py"),
                 os.path.join(_ROOT, "vercel-app", "api", "search.py")):
        src = open(path).read()
        m = re.search(r"def lineage\(.*?\n    return edges", src, re.S)
        assert m, f"{path}: lineage() not found"
        for field in ("era_bucket", "mentor", "published_at"):
            assert f'"{field}"' in m.group(0), (
                f"{path}: lineage() does not return {field!r}")


def test_completion_fetch_carries_mentor():
    """fetch_person_edges feeds the same timeline; omitting mentor there drops
    the 'under …' line from rows whose stored edge names one."""
    for path in (os.path.join(_ROOT, "ui", "server.py"),
                 os.path.join(_ROOT, "vercel-app", "api", "search.py")):
        src = open(path).read()
        m = re.search(r"def fetch_person_edges\(.*?\n    return out", src, re.S)
        assert m, f"{path}: fetch_person_edges() not found"
        body = m.group(0)
        assert '"mentor"' in body, f"{path}: fetch_person_edges omits mentor"
        assert '"published_at"' in body, f"{path}: fetch_person_edges omits published_at"
