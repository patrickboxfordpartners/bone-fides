"""Explorer UX: the dossier leads, booking links sit in it, nothing is off-palette.

A review of the live explorer found the dossier starting below the fold, the
verified booking pages reachable only from a map popup, a developer timing in
the reader's line, two browser-blue controls, and an empty dark panel when the
map could not start. These tests keep each fix in place.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(_ROOT, "ui", "explorer.html"), encoding="utf-8").read()
MAPJS = open(os.path.join(_ROOT, "ui", "map.js"), encoding="utf-8").read()


def _booking_for(query, venues):
    rt = next((p for p in (shutil.which(n) for n in ("node", "bun", "deno")) if p), None)
    if not rt:
        pytest.skip("no JS runtime available")
    fns = "\n".join(
        re.search(rf"function {name}\([^)]*\)\{{.*?\n\}}\n", HTML, re.S).group(0)
        for name in ("bookingKey", "bookingFor"))
    script = fns + f"\nconsole.log(JSON.stringify(bookingFor({json.dumps(query)}, {json.dumps(venues)})));\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(script)
    try:
        args = [rt, "run", f.name] if os.path.basename(rt) != "node" else [rt, f.name]
        out = subprocess.run(args, capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)
    finally:
        os.unlink(f.name)


OT = {"opentable": "https://www.opentable.com/r/x-san-francisco"}


def test_dossier_booking_matches_the_pin_that_is_this_kitchen():
    assert _booking_for("Zuni Café", [{"name": "Zuni Cafe", "lineage_name": "Zuni Cafe", "booking": OT}]) == OT
    # the map links the pin to this lineage name and the pin's own name extends it
    assert _booking_for("Kin Khao", [{"name": "Kin Khao Thai Eatery", "lineage_name": "Kin Khao", "booking": OT}]) == OT


def test_dossier_booking_ignores_a_loose_lineage_link():
    # "Balboa" is linked to a produce market; Balboa Cafe's page is not Balboa's
    venues = [{"name": "Balboa Produce", "lineage_name": "Balboa"},
              {"name": "Balboa Cafe", "lineage_name": "Balboa Cafe", "booking": OT}]
    assert _booking_for("Balboa", venues) is None
    # a pin merely linked to the lineage name, with an unrelated own name
    assert _booking_for("Gusto", [{"name": "Buon Gusto", "lineage_name": "Gusto", "booking": OT}]) is None
    assert _booking_for("", [{"name": "", "booking": OT}]) is None


def test_booking_row_is_for_kitchens_and_filled_after_render():
    assert '<div class="bookrow" id="bookrow"' in HTML
    assert re.search(r"\$\{isPersonQuery \? '' : '<div class=\"bookrow\"", HTML), "a chef dossier has no booking row"
    assert "fillBooking(q);" in HTML
    # a slower /api/venues must not fill a newer dossier's row
    assert "row.dataset.q !== q" in HTML


def test_reader_line_has_no_developer_timing():
    assert "resolved in" not in HTML.split("<script>", 1)[1].replace("Time is resolved in two levels", "")


def test_rail_head_folds_only_while_a_dossier_is_shown():
    assert "body.has-dossier .tagline, body.has-dossier #chips { display: none; }" in HTML
    m = re.search(r"new MutationObserver\(\(\) => \{(.*?)\}\)\.observe\(CARD", HTML, re.S)
    assert m, "the dossier-mode observer is gone"
    body = m.group(1)
    assert "classList.add('has-dossier')" in body and "classList.remove('has-dossier')" in body
    # loading keeps the current state so the head does not jump between traces
    assert ".loading" in body


def test_no_browser_default_colours():
    assert re.search(r"\.pedmethod \{[^}]*color: inherit", HTML)
    cancel = re.search(r"input#q::-webkit-search-cancel-button \{[^}]*\}", HTML)
    assert cancel and "appearance: none" in cancel.group(0) and "var(--dim)" in cancel.group(0)


def test_score_says_what_it_measures_without_a_hover():
    assert '<div class="pednote">How well documented this kitchen is, not how good it is.</div>' in HTML


def test_map_failure_hands_the_page_to_the_rail():
    handler = re.search(r"window\.__bfMapUnavailable = \(\) => \{(.*?)\};", HTML, re.S).group(1)
    assert "classList.add('nomap')" in handler
    assert "body.nomap .stage { display: none; }" in HTML
    # the constructor throws without WebGL; map.js must report it, not die
    ctor = re.search(r"try \{\s*map = new mapboxgl\.Map\(.*?\} catch \(e\) \{(.*?)\n    \}", MAPJS, re.S)
    assert ctor and "__bfMapUnavailable" in ctor.group(1) and "el.remove()" in ctor.group(1)


def test_touch_layout_enlarges_small_targets():
    block = re.search(r"@media \(max-width: 900px\), \(pointer: coarse\) \{(.*?)\n  \}\n", HTML, re.S)
    assert block, "the touch-target block is gone"
    css = block.group(1)
    for sel in (".watchbtn", ".copybtn", ".rchip", ".chip::before", ".vchip::before",
                ".flaglink::before", ".chef .src a::before"):
        assert sel in css, sel
    assert "height: 44px" in css and "min-height: 40px" in css


def test_small_labels_meet_the_design_floor():
    sizes = [float(x) for x in re.findall(r"font-size: ?([\d.]+)px", HTML.split("@media print", 1)[0])]
    assert min(sizes) >= 10.5, "docs/DESIGN.md: labels are 10.5px or larger"
