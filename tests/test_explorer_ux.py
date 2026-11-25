"""Explorer UX: the dossier leads, booking links sit in it, nothing is off-palette.

A review of the live explorer found the dossier starting below the fold, the
verified booking pages reachable only from a map popup, a developer timing in
the reader's line, two browser-blue controls, and an empty dark panel when the
map could not start. These tests keep each fix in place.
"""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(_ROOT, "ui", "explorer.html"), encoding="utf-8").read()
MAPJS = open(os.path.join(_ROOT, "ui", "map.js"), encoding="utf-8").read()


def test_dossier_booking_comes_from_the_search_payload():
    """The explorer must not match restaurants to booking pages itself: a name
    prefix rule put Palette Tea House's page on the Palette dossier and Camino
    Alto's on Camino. It renders only what /api/search verified."""
    assert "dossierBooking = d.booking || null;" in HTML
    assert "${isPersonQuery ? '' : bookingRow(dossierBooking)}" in HTML, "a chef dossier has no booking row"
    row = re.search(r"function bookingRow\(links\)\{(.*?)\n\}\n", HTML, re.S).group(1)
    assert "esc(links[key])" in row and "^https:" in row
    # an empty row must not exist at all (a flex row ignores `hidden`)
    assert "return html ? `<div class=\"bookrow\">${html}</div>` : '';" in row
    for gone in ("bookingFor", "fillBooking", "startsWith(k)"):
        assert gone not in HTML


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


def test_touch_layout_enlarges_small_targets_without_overlap():
    block = re.search(r"@media \(max-width: 900px\), \(pointer: coarse\) \{(.*?)\n  \}\n", HTML, re.S)
    assert block, "the touch-target block is gone"
    css = block.group(1)
    for sel in (".watchbtn", ".copybtn", ".rchip", ".chip::before", ".vchip::before",
                ".flaglink::before", ".chef .src a::before"):
        assert sel in css, sel
    assert "min-height: 40px" in css
    # a hit area grows 10px above and below its link; every row that stacks
    # such links must open by at least 20px, or one area covers the next line
    grow = int(re.search(r"inset: -(\d+)px -(\d+)px", css).group(1))
    rows = re.search(r"([^{}]*)\{ row-gap: (\d+)px; \}", css)
    assert int(rows.group(2)) >= 2 * grow
    # every container that wraps or stacks venue links, including the undated
    # timeline rows, must be in that rule or carry the clearance itself
    for sel in (".chips", ".chain", ".tlvenues", ".tlundated .urow", ".tlundated .urowmain", ".treelist .trow"):
        assert sel in rows.group(1), sel
    assert int(re.search(r"\.tlbody \{ padding-bottom: (\d+)px; \}", css).group(1)) >= 2 * grow
    assert int(re.search(r"\.tlundated \.urow \{ margin-bottom: (\d+)px; \}", css).group(1)) >= 2 * grow
    # "View as tree" list rows stack venue links too: top + bottom padding of
    # two neighbours must cover both hit areas
    assert int(re.search(r"\.treelist \.trow \{ padding-block: (\d+)px; \}", css).group(1)) >= grow
    # the Instagram badge sits on the name line just above the first venue
    # link: its hit area must come after the shared rule and not reach down
    badge = re.search(r"\.igbadge::before \{ inset: -(\d+)px -(\d+)px (-?\d+)(?:px)?; \}", css)
    assert badge, "the badge-specific hit area is gone"
    assert int(badge.group(3)) == 0, "the badge hit area must not extend downward"
    assert int(badge.group(1)) >= 2 * grow, "it grows upward by the full amount instead"
    assert css.index(".igbadge::before { inset:") > css.index("inset: -10px -3px"), "later rule wins the cascade"
    side = int(re.search(r"inset: -(\d+)px -(\d+)px", css).group(2))
    col_gaps = [int(g) for g in re.findall(r"\.(?:chips|chain|tlvenues|urow|urowmain) \{[^}]*gap: \d+px (\d+)px", HTML)]
    assert col_gaps and min(col_gaps) >= 2 * side, col_gaps


def test_small_labels_meet_the_design_floor():
    sizes = [float(x) for x in re.findall(r"font-size: ?([\d.]+)px", HTML.split("@media print", 1)[0])]
    assert min(sizes) >= 10.5, "docs/DESIGN.md: labels are 10.5px or larger"


def test_a_late_suggestion_cannot_reopen_over_the_dossier():
    """Typing a name and pressing Enter before the suggest call returned left
    the suggestion list open on top of the dossier header."""
    hide = re.search(r"function hideSugg\(\)\{(.*?)\}", HTML).group(1)
    assert "clearTimeout(sugTimer)" in hide and "sugSeq++" in hide
    assert "if(mine !== sugSeq) return;" in HTML
