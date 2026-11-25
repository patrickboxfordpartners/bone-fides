"""Sync the shared chrome into every page (docs/flagship/plan.md section 7).

The canonical copy is ui/_chrome.html. Each page holds blocks between
markers; this script replaces each block's content with the canonical copy
and sets aria-current="page" on the page's own nav link. The output is
committed; the deploy does not run this script.

Blocks and their markers:
  chrome    between /* bf:chrome */ and /* /bf:chrome */   (CSS)
  header    between <!-- bf:header --> and <!-- /bf:header -->
  footer    between <!-- bf:footer --> and <!-- /bf:footer -->
  chrome-js between <!-- bf:chrome-js --> and <!-- /bf:chrome-js -->

A page syncs the blocks listed for it in PAGES. The landing page takes the
header only; its footer is part of the landing rebuild (plan section 12).

Run from the repo root:  .venv/bin/python scripts/sync_chrome.py
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = os.path.join(BASE, "ui", "_chrome.html")

# page file -> (own route, blocks it carries)
PAGES = {
    "landing.html": ("/", ["chrome", "header", "chrome-js"]),
    "explorer.html": ("/explorer", ["chrome", "header", "footer", "chrome-js"]),
    "tree.html": ("/tree", ["chrome", "header", "footer", "chrome-js"]),
    "connect.html": ("/connect", ["chrome", "header", "footer", "chrome-js"]),
    "method.html": ("/method", ["chrome", "header", "footer", "chrome-js"]),
}


def _canonical_blocks():
    src = open(CHROME, encoding="utf-8").read()
    out = {}
    m = re.search(r"/\* bf:chrome \*/(.*?)/\* /bf:chrome \*/", src, re.S)
    out["chrome"] = m.group(1)
    for name in ("header", "footer", "chrome-js"):
        m = re.search(r"<!-- bf:%s -->(.*?)<!-- /bf:%s -->" % (name, name), src, re.S)
        out[name] = m.group(1)
    return out


def _replace_block(text, name, content):
    if name == "chrome":
        pat = r"/\* bf:chrome \*/.*?/\* /bf:chrome \*/"
        repl = "/* bf:chrome */%s/* /bf:chrome */" % content
    else:
        pat = r"<!-- bf:%s -->.*?<!-- /bf:%s -->" % (name, name)
        repl = "<!-- bf:%s -->%s<!-- /bf:%s -->" % (name, content, name)
    new, n = re.subn(pat, lambda m: repl, text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("page is missing the bf:%s markers" % name)
    return new


def sync_page(path, route, blocks, canon):
    text = open(path, encoding="utf-8").read()
    for name in blocks:
        text = _replace_block(text, name, canon[name])
    if "header" in blocks:
        head = re.search(r"<!-- bf:header -->(.*?)<!-- /bf:header -->",
                         text, re.S).group(1)
        marked = re.sub(
            r'<a href="([^"]*)">',
            lambda m: ('<a href="%s" aria-current="page">' % m.group(1)
                       if m.group(1) == route else m.group(0)),
            head)
        text = text.replace(head, marked, 1)
    open(path, "w", encoding="utf-8").write(text)
    print("synced", os.path.basename(path), "(%s)" % ", ".join(blocks))


def main():
    canon = _canonical_blocks()
    for page, (route, blocks) in PAGES.items():
        sync_page(os.path.join(BASE, "ui", page), route, blocks, canon)
    print("chrome synced into %d pages" % len(PAGES))


if __name__ == "__main__":
    main()
