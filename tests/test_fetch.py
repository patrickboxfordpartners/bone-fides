from src.fetch import extract_text_from_html

FIXTURE = """<html><head><title>Say bye to Betelnut</title>
<script>var junk = "ignore me";</script><style>.a{color:red}</style></head>
<body><nav>Subscribe | Menu | Login</nav>
<article><h1>Say bye to Betelnut</h1><p>Chef Alexander Ong departs after a 20-year run.</p>
<p>The Cow Hollow institution closes Sunday.</p></article>
<footer>Copyright 2015</footer></body></html>"""

def test_extracts_text_dropping_script_style_nav():
    out = extract_text_from_html(FIXTURE)
    assert "Alexander Ong departs" in out
    assert "Cow Hollow institution" in out
    assert "ignore me" not in out
    assert "color:red" not in out
    assert "Subscribe | Menu" not in out
    assert "Copyright 2015" not in out

def test_returns_title_when_present():
    out = extract_text_from_html(FIXTURE)
    assert out.startswith("TITLE: Say bye to Betelnut")
