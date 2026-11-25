"""The rebuilt landing page (plan section 12).

Static checks on ui/landing.html and the share assets (section 14): the
hero reserves its drawing height, the two actions exist, the three feature
blocks link their pages, the proof block keeps the n-* slots and its gate
figures, the consumer loop carries the search form and the three steps,
and every page ships the share tags with the absolute brand-card URL.
"""
import os
import re
import struct

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def _page(name="landing.html"):
    return open(os.path.join(_ROOT, "ui", name), encoding="utf-8").read()


def test_the_hero_reserves_the_height_of_the_drawing():
    p = _page()
    assert "min-height:520px" in p, "the rings box must reserve its height"
    assert '<svg id="hero-svg"' in p


def test_the_hero_offers_both_actions():
    p = _page()
    assert 'id="act-tree"' in p and "Open the tree" in p
    assert "Trace a line" in p


def test_the_three_feature_blocks_link_their_pages():
    p = _page()
    for needle in ('id="way-tree"', 'id="way-connect"', 'id="way-ledger"'):
        assert needle in p
    assert 'href="/tree"' in p and 'href="/connect"' in p and 'href="/ledger"' in p


def test_the_proof_block_carries_the_gate_figures_and_links():
    p = _page()
    assert 'id="p-displayed"' in p, "the displayed count sits beside moves on record"
    assert 'id="p-precision"' in p, "the measured precision sits beside the gate"
    assert 'href="/method"' in p and 'href="/numbers"' in p
    # the n-* slots show em dashes until the payload arrives
    for id_ in ("n-edges", "n-people", "n-venues", "n-sources"):
        slot = re.search(r'id="%s">&mdash;' % id_, p)
        assert slot, "the %s slot must start empty" % id_


def test_the_consumer_loop_searches_the_explorer():
    p = _page()
    assert '<form class="loopform" action="/explorer" method="get"' in p
    assert 'name="q"' in p
    for step in ("1 &middot; Explore", "2 &middot; Trust", "3 &middot; Book"):
        assert step in p, "missing loop step %s" % step


def test_the_landing_carries_the_shared_footer():
    p = _page()
    assert '<!-- bf:footer -->' in p and '<footer class="bf-foot">' in p


def test_the_hero_drawing_uses_the_shared_renderer():
    p = _page()
    assert "L.renderRings" in p, "the hero draws through lineage.js"
    assert "{ maxGen: 2 }" in p, "the hero draws two moves"


def test_every_page_ships_the_share_tags():
    og_img = 'content="https://bone-fides.vercel.app/og.png"'
    for name in ("landing.html", "explorer.html", "tree.html", "connect.html",
                 "ledger.html", "numbers.html", "method.html"):
        p = _page(name)
        assert 'property="og:title"' in p, name
        assert 'property="og:description"' in p, name
        assert og_img in p, name
        assert 'name="twitter:card"' in p, name


def test_the_brand_card_exists_at_1200_by_630():
    path = os.path.join(_ROOT, "ui", "og.png")
    assert os.path.exists(path), "ui/og.png is missing"
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", head[16:24])
    assert (w, h) == (1200, 630), "the card must be 1200x630, got %dx%d" % (w, h)


def test_the_build_ships_the_brand_card():
    b = open(os.path.join(_ROOT, "vercel-app", "build.sh"), encoding="utf-8").read()
    assert "og.png" in b
