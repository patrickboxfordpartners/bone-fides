"""Every publisher photo is captioned with the publication that published it.

The corpus renders the CITED ARTICLE's own photograph on each chef card. Those
photos belong to SFGate, the Chronicle and Eater — not to us and not to the
restaurant. Before this, 2,219 of them rendered as a bare <img> with the article
credit sitting in a separate block, so nothing on screen tied the picture to its
source.

These tests execute the real `outletName()` from explorer.html in a JS runtime,
and check the markup invariant by reading the card template. Reading the source
is not enough on its own (a broken template can still contain the word
"photo"), so the runtime check is the load-bearing one.
"""
import os, re, shutil, subprocess, sys, tempfile
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
HTML = os.path.join(_ROOT, "ui", "explorer.html")


def _html():
    return open(HTML, encoding="utf-8").read()


def _runtime():
    for name, args in (("bun", ["run"]), ("deno", ["run", "--quiet"]), ("node", [])):
        p = shutil.which(name)
        if p:
            return [p] + args
    return None


def _outlet_fn():
    src = _html()
    m = re.search(r"function outletName\([^)]*\)\{.*?\n\}\n", src, re.S)
    assert m, "outletName() not found in explorer.html"
    return m.group(0)


def _call(expr):
    rt = _runtime()
    if not rt:
        pytest.skip("no JS runtime (bun/deno) available")
    script = (
        "function hostOf(u){ try { return new URL(u).hostname.replace('www.',''); } catch(e){ return u; } }\n"
        + _outlet_fn()
        + f"\nconsole.log(JSON.stringify({expr}));\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(script)
        path = f.name
    try:
        out = subprocess.run(rt + [path], capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()
    finally:
        os.unlink(path)


def test_sfgate_photo_credits_sfgate():
    got = _call("outletName('https://www.sfgate.com/restaurants/article/x.php','sfgate')")
    assert got == '"SFGate"'


def test_eater_photo_credits_eater():
    got = _call("outletName('https://sf.eater.com/2020/1/1/1/x','eater')")
    assert got == '"Eater SF"'


def test_chronicle_photo_credits_the_chronicle():
    got = _call("outletName('https://www.sfchronicle.com/food/article/x','sfchronicle')")
    assert got == '"San Francisco Chronicle"'


def test_unknown_host_falls_back_to_the_hostname():
    # A publisher we have no label for must still be named, not credited to a
    # guess. hostOf() strips the leading www.
    got = _call("outletName('https://www.example-paper.com/a/b','other')")
    assert got == '"example-paper.com"'


def test_eater_label_never_renames_a_foreign_host():
    # Same rule srcBadge enforces: a stored "eater" label must not relabel a
    # different publisher's photo.
    got = _call("outletName('https://www.sfchronicle.com/x','eater')")
    assert got == '"San Francisco Chronicle"'


def test_image_is_wrapped_in_a_captioned_figure():
    # The caption lives in `imgCredit` and is interpolated into the figure, so
    # check the figure references it rather than that both strings appear in
    # the same literal.
    src = _html()
    m = re.search(r"const img = pivot\.source_image\s*\?\s*`(.*?)`\s*:", src, re.S)
    assert m, "image template not found"
    tpl = m.group(1)
    assert "<figure" in tpl and "evfig" in tpl, "photo must be a figure"
    assert "${imgCredit}" in tpl, "the figure must interpolate the credit line"


def test_credit_line_is_a_figcaption():
    src = _html()
    m = re.search(r"const imgCredit = pivot\.source_url\s*\n?\s*\?\s*`(.*?)`", src, re.S)
    assert m, "imgCredit template not found"
    tpl = m.group(1)
    assert "<figcaption" in tpl and "imgcredit" in tpl
    assert "photo:" in tpl, "the caption must read as a credit, not a bare name"


def test_credit_links_to_the_cited_article():
    src = _html()
    m = re.search(r"const imgCredit = pivot\.source_url\s*\n?\s*\?\s*`(.*?)`", src, re.S)
    assert m, "imgCredit template not found"
    tpl = m.group(1)
    assert 'href="${esc(pivot.source_url)}"' in tpl
    assert "outletName(" in tpl


def test_broken_photo_hides_its_credit_too():
    # An <img> that 404s is hidden by the global error handler. If only the img
    # were hidden, the caption would point at nothing.
    src = _html()
    m = re.search(r"document\.addEventListener\('error'.*?\}, true\);", src, re.S)
    assert m, "image error handler not found"
    handler = m.group(0)
    assert "closest('.evfig')" in handler, "handler must hide the whole figure"
