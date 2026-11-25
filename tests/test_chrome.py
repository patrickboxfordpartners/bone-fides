"""The shared chrome stays in sync (docs/flagship/plan.md section 7).

The canonical copy is ui/_chrome.html. Each page holds marked blocks; this
test fails when a copied block drifts. The only permitted difference is
aria-current="page" on the page's own nav link.
"""
import os
import re

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
CHROME = os.path.join(_ROOT, "ui", "_chrome.html")

PAGES = {
    "landing.html": ("/", ["chrome", "header", "chrome-js"]),
    "explorer.html": ("/explorer", ["chrome", "header", "footer", "chrome-js"]),
    "tree.html": ("/tree", ["chrome", "header", "footer", "chrome-js"]),
    "connect.html": ("/connect", ["chrome", "header", "footer", "chrome-js"]),
    "ledger.html": ("/ledger", ["chrome", "header", "footer", "chrome-js"]),
    "numbers.html": ("/numbers", ["chrome", "header", "footer", "chrome-js"]),
    "method.html": ("/method", ["chrome", "header", "footer", "chrome-js"]),
}


def _canonical():
    src = open(CHROME, encoding="utf-8").read()
    out = {}
    m = re.search(r"/\* bf:chrome \*/(.*?)/\* /bf:chrome \*/", src, re.S)
    out["chrome"] = m.group(1)
    for name in ("header", "footer", "chrome-js"):
        m = re.search(r"<!-- bf:%s -->(.*?)<!-- /bf:%s -->" % (name, name), src, re.S)
        out[name] = m.group(1)
    return out


def _page_block(path, name):
    text = open(path, encoding="utf-8").read()
    if name == "chrome":
        m = re.search(r"/\* bf:chrome \*/(.*?)/\* /bf:chrome \*/", text, re.S)
    else:
        m = re.search(r"<!-- bf:%s -->(.*?)<!-- /bf:%s -->" % (name, name), text, re.S)
    return m.group(1) if m else None


@pytest.mark.parametrize("page", sorted(PAGES))
def test_every_page_holds_its_blocks(page):
    path = os.path.join(_ROOT, "ui", page)
    for name in PAGES[page][1]:
        assert _page_block(path, name) is not None, "%s lacks bf:%s" % (page, name)


@pytest.mark.parametrize("page", sorted(PAGES))
def test_blocks_match_the_canonical_copy(page):
    path = os.path.join(_ROOT, "ui", page)
    canon = _canonical()
    for name in PAGES[page][1]:
        got = _page_block(path, name)
        if name == "header":
            # the only permitted difference: aria-current on the page's link
            route = PAGES[page][0]
            marked = re.sub(
                r'<a href="([^"]*)">',
                lambda m: ('<a href="%s" aria-current="page">' % m.group(1)
                          if m.group(1) == route else m.group(0)),
                canon["header"])
            assert got == marked, "%s: bf:header differs from _chrome.html" % page
        else:
            assert got == canon[name], "%s: bf:%s differs from _chrome.html" % (page, name)


@pytest.mark.parametrize("page", sorted(PAGES))
def test_the_page_marks_its_own_link(page):
    path = os.path.join(_ROOT, "ui", page)
    route = PAGES[page][0]
    head = _page_block(path, "header")
    assert head is not None
    if route == "/":
        return  # the landing page owns no nav link
    m = re.search(r'<a href="%s" aria-current="page">' % re.escape(route), head)
    assert m, "%s does not mark its own nav link" % page


def test_the_header_lists_only_routes_that_exist():
    canon = _canonical()["header"]
    for href in re.findall(r'<a href="(/[^"]*)">', canon):
        target = os.path.join(_ROOT, "ui", href.strip("/").split("?")[0] + ".html")
        assert os.path.exists(target), "nav links to %s, which has no page" % href


def test_the_footer_lists_only_routes_that_exist():
    canon = _canonical()["footer"]
    for href in re.findall(r'<a href="(/[^"]*)">', canon):
        target = os.path.join(_ROOT, "ui", href.strip("/").split("?")[0] + ".html")
        assert os.path.exists(target), "footer links to %s, which has no page" % href


def test_the_menu_button_is_hidden_without_javascript():
    canon = _canonical()["header"]
    m = re.search(r'<button type="button" class="bf-menu" hidden', canon)
    assert m, "the Menu button must carry the hidden attribute in markup"


def test_sync_script_is_idempotent():
    import subprocess
    import sys
    before = {}
    for page in PAGES:
        before[page] = open(os.path.join(_ROOT, "ui", page), encoding="utf-8").read()
    subprocess.run([sys.executable, "scripts/sync_chrome.py"], cwd=_ROOT,
                   check=True, capture_output=True)
    for page in PAGES:
        after = open(os.path.join(_ROOT, "ui", page), encoding="utf-8").read()
        assert after == before[page], "sync_chrome.py changed %s" % page
