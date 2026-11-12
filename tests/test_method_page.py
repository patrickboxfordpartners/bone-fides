"""The /method page must describe a corpus that actually exists.

Every figure on that page is a claim about the data. The failure mode this
locks is subtle and damaging: a methodology page that states a coverage rate
the corpus does not have is worse than no page at all, because it dresses an
inaccuracy in the language of rigour.
"""
import ast
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_UI_PATH = os.path.join(_ROOT, "ui", "server.py")
_VERCEL_PATH = os.path.join(_ROOT, "vercel-app", "api", "search.py")
_METHOD_HTML = os.path.join(_ROOT, "ui", "method.html")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _funcs(path):
    tree = ast.parse(open(path).read())
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_method_endpoint_exists_in_both_twins():
    for path in (_UI_PATH, _VERCEL_PATH):
        assert "method" in _funcs(path), f"{path}: no method() endpoint"


def test_method_covers_every_field_the_page_displays():
    """The page shows these coverage rates; the endpoint must return them all,
    or the page renders a dash where a number should be. The field list lives
    in a module constant, so check the constant and the loop that uses it."""
    for path in (_UI_PATH, _VERCEL_PATH):
        tree = ast.parse(open(path).read())
        consts = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign)
                  for t in n.targets if isinstance(t, ast.Name)}
        fields = ast.literal_eval(consts["_COVERAGE_FIELDS"])
        for field in ("date", "era_bucket", "venue_hoods", "action", "mentor"):
            assert field in fields, (
                f"{path}: _COVERAGE_FIELDS omits {field!r}, which /method renders")
        assert "_COVERAGE_FIELDS" in ast.unparse(_funcs(path)["method"]), (
            f"{path}: method() no longer iterates _COVERAGE_FIELDS")


def test_method_reuses_stats_for_shared_counts():
    """The counts that also appear on the landing page must come from stats(),
    not a second computation — two code paths can disagree."""
    for path in (_UI_PATH, _VERCEL_PATH):
        src = ast.unparse(_funcs(path)["method"])
        assert "stats(es)" in src, (
            f"{path}: method() recomputes shared counts instead of reusing "
            f"stats(), so /method and the landing page can disagree")


def test_method_reports_outlet_tiers():
    for path in (_UI_PATH, _VERCEL_PATH):
        src = ast.unparse(_funcs(path)["method"])
        for tier in ("sfchronicle", "sfgate", "eater"):
            assert tier in src, f"{path}: method() omits the {tier} tier"


def test_method_page_states_the_score_measures_documentation_not_quality():
    """The rename from 'pedigree' exists because the old name implied a
    judgement about the kitchen. If that sentence ever leaves the page, the
    rename has lost its reason."""
    html = open(_METHOD_HTML).read().lower()
    assert "measures documentation, not quality" in html or \
           "documentation, not quality" in html, (
        "method.html no longer states that the score measures documentation "
        "rather than culinary quality")


def test_method_page_documents_the_fields_it_discloses():
    html = open(_METHOD_HTML).read().lower()
    for topic in ("mentor", "date", "same name", "published"):
        assert topic in html, f"method.html no longer discusses {topic!r}"


def test_method_page_reads_tiers_from_the_payload_root():
    """tiers is a sibling of coverage in the API payload, not a member of it.

    The page originally read `c.tiers` where `c = d.coverage`. It parsed, it
    ran, it threw nothing — and every outlet figure silently rendered 0 while
    the copy-pasted "Measuring…" note stayed stuck. Only a real browser caught
    it, because the JS is inline and no test ever executed it.
    """
    html = open(_METHOD_HTML).read()
    assert "d.tiers" in html, (
        "method.html must read tiers from the payload root (d.tiers)")
    assert "c.tiers" not in html and "cov.tiers" not in html, (
        "method.html reads tiers from the coverage object again — it is a "
        "sibling field, so this yields undefined and renders zeros")


def test_method_page_coverage_reads_come_from_the_coverage_object():
    """Guard the other direction: coverage fields live under d.coverage."""
    html = open(_METHOD_HTML).read()
    assert "d.coverage" in html
    for field in ("era_bucket", "venue_hoods", "mentor"):
        assert f"cov.{field}" in html, (
            f"method.html no longer reads {field} from the coverage object")


def test_method_page_explains_kitchen_names_are_not_restaurants():
    """The venue count folds normalized names but does not resolve aliases.
    That caveat must stay on the page — it is the honest reading of the number."""
    html = open(_METHOD_HTML).read().lower()
    assert "distinct normalized names" in html or "normalized names" in html, (
        "method.html dropped the normalized-names caveat")
    assert "tartine" in html, (
        "method.html dropped the concrete alias example that makes the caveat "
        "understandable")


def test_no_display_surface_still_calls_it_a_pedigree_score():
    """The rename is only real if every surface moved. CSS class names are
    fine; a visible label is not."""
    for name in ("landing.html", "explorer.html", "method.html"):
        html = open(os.path.join(_ROOT, "ui", name)).read()
        assert "Pedigree score" not in html, (
            f"{name} still shows the old 'Pedigree score' label")
        assert "Bone Fides score" not in html, (
            f"{name} still shows the old 'Bone Fides score' label")
