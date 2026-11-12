"""Twin parity: ui/server.py and vercel-app/api/search.py must agree.

The two files are hand-maintained copies of the same dossier logic. Nothing
enforced that, and they drifted: prod's fetch_person_edges returned
source_image while local's did not (same query, different page depending on
which runtime served it), and local's identity() carried a person_fix() seam
prod lacked.

This test AST-compares every function the two modules share and fails on any
structural difference. It is deliberately stricter than a behavioural test:
the point is that a change to one twin cannot land without the other.

Legitimate divergences are declared in ALLOWED with the reason. Adding an
entry is a decision to accept divergent behaviour — write it down.
"""
import ast
import importlib.util
import inspect
import os
import textwrap

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_UI_PATH = os.path.join(_ROOT, "ui", "server.py")
_VERCEL_PATH = os.path.join(_ROOT, "vercel-app", "api", "search.py")

# Functions permitted to differ, with the reason. Keep this list short and
# specific: every entry is a place where the two runtimes genuinely cannot
# share code, never a place they merely happened to diverge.
ALLOWED = {
    # venues_geo reads bundled JSON from different roots (_HERE vs ROOT) and
    # the Vercel copy takes es=None because it never touches ES.
    "venues_geo",
    # _facet_probe: local imports find_edges lazily from src.es to avoid a
    # circular import at module load; prod defines find_edges inline.
    "_facet_probe",
}


def _strip_docstrings(tree):
    """Docstrings are documentation, not behaviour. Compare code only."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return tree


def _functions(path):
    tree = _strip_docstrings(ast.parse(open(path).read()))
    return {n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_UI_FUNCS = _functions(_UI_PATH)
_VERCEL_FUNCS = _functions(_VERCEL_PATH)
_SHARED = sorted(set(_UI_FUNCS) & set(_VERCEL_FUNCS))


def test_the_twins_actually_share_code():
    """Guard the guard: if a rename makes _SHARED empty or tiny, the parity
    test would pass vacuously while the files diverged completely."""
    assert len(_SHARED) > 25, (
        f"only {len(_SHARED)} shared top-level functions between the twins — "
        "the comparison is no longer meaningful. Did a function get renamed "
        "in one file?")


@pytest.mark.parametrize("name", _SHARED)
def test_twin_function_is_identical(name):
    if name in ALLOWED:
        pytest.skip(f"{name}: documented divergence")
    local = ast.dump(_UI_FUNCS[name], include_attributes=False)
    vercel = ast.dump(_VERCEL_FUNCS[name], include_attributes=False)
    assert local == vercel, (
        f"{name} differs between ui/server.py and "
        f"vercel-app/api/search.py.\n"
        f"The two runtimes would answer the same query differently.\n"
        f"Sync the function, or add '{name}' to ALLOWED with a reason if the "
        f"divergence is forced by the runtime.")


def test_every_allowed_divergence_names_a_real_function():
    """A stale ALLOWED entry silently exempts nothing and hides that the
    exemption was never needed (or that the function was deleted)."""
    stale = [n for n in ALLOWED if n not in _SHARED]
    assert not stale, f"ALLOWED names functions not shared by both twins: {stale}"


def _module_constants(tree):
    """Module-level UPPERCASE assignments, by name and literal value."""
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if (isinstance(tgt, ast.Name) and tgt.id.isupper()
                    and isinstance(node.value, ast.Constant)):
                out[tgt.id] = node.value.value
    return out


@pytest.mark.parametrize("path", [_UI_PATH, _VERCEL_PATH],
                         ids=["ui/server.py", "vercel-app/api/search.py"])
def test_no_function_references_an_undefined_module_constant(path):
    """Catch the bug this test file was written to prevent, one layer up.

    A parity test compares function bodies; it cannot see that a body now
    calls a module-level name the file never defines. That is exactly how
    vercel-app/api/search.py briefly shipped referencing _ERA_COVERAGE after
    the literals were swapped for names — syntactically fine, NameError at
    request time, invisible to any test that only read the AST of functions.

    Every UPPERCASE name read anywhere in the file must be bound somewhere
    in that file — module scope, an import, or a local like KEEP_TYPES.
    Scope is not resolved precisely (a name bound in one function would
    mask the same name read in another); that fuzziness is the price of a
    dependency-free check, and it still catches the real case: a name that
    exists nowhere at all.
    """
    tree = ast.parse(open(path).read())
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                bound.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            for a in node.args.args + node.args.kwonlyargs:
                bound.add(a.arg)
        elif isinstance(node, ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)

    referenced = {n.id for n in ast.walk(tree)
                  if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                  and n.id.isupper()}
    undefined = sorted(referenced - bound)
    assert not undefined, (
        f"{path} references UPPERCASE names bound nowhere in the file: "
        f"{undefined}. This raises NameError at request time, not import time.")


def test_coverage_constants_agree_between_twins():
    """The two runtimes must disclose the same coverage numbers, or the same
    filtered dossier reads differently depending on who served it."""
    ui = _module_constants(ast.parse(open(_UI_PATH).read()))
    vercel = _module_constants(ast.parse(open(_VERCEL_PATH).read()))
    for name in ("_ERA_COVERAGE", "_HOOD_COVERAGE"):
        assert name in ui and name in vercel, f"{name} missing from a twin"
        assert ui[name] == vercel[name], (
            f"{name} differs: ui={ui[name]!r} vercel={vercel[name]!r}")


def test_both_twins_import_cleanly():
    """A module that parses but cannot execute is still broken. Load both."""
    for name, path in (("parity_ui_import", _UI_PATH),
                       ("parity_vercel_import", _VERCEL_PATH)):
        mod = _load(name, path)
        assert hasattr(mod, "assemble_dossier")
        assert hasattr(mod, "stats")


# Assets the deploy serves that originate in ui/. Keep in sync with
# vercel-app/build.sh — the bug this locks is landing.html being served from
# vercel-app/ but never copied there, so it drifted for every content change.
_DEPLOYED_FROM_UI = ("landing.html", "explorer.html", "map.js",
                     "city_venues.json", "venues_geo.json")


def test_build_copies_every_ui_asset_the_deploy_serves():
    """Any front-end asset served by Vercel must have a copy rule in build.sh.

    landing.html was absent from build.sh's copy list. The deploy kept serving
    a committed copy, so the live homepage showed 9,309 moves, 799 kitchens,
    and a pedigree score of 73 while ui/ had moved on. Nothing detected it
    because the drift was between a source file and an un-copied artifact.
    """
    build = open(os.path.join(_ROOT, "vercel-app", "build.sh")).read()
    missing = [f for f in _DEPLOYED_FROM_UI if f"ui/{f}" not in build]
    assert not missing, (
        f"build.sh never copies {missing} from ui/ — the deployed copy will "
        f"drift from the source on every edit.")


@pytest.mark.parametrize("asset", _DEPLOYED_FROM_UI)
def test_copy_listed_assets_start_life_identical(asset):
    """Committed copies must match ui/ at rest.

    build.sh re-copies them at deploy time when ../ui/ exists, but CLI deploys
    from a shallow checkout fall back to the committed copy. A committed copy
    that disagrees with ui/ means two different sites depending on how it was
    built.
    """
    a = os.path.join(_ROOT, "ui", asset)
    b = os.path.join(_ROOT, "vercel-app", asset)
    if not (os.path.exists(a) and os.path.exists(b)):
        pytest.skip(f"{asset} not present in both trees")
    assert open(a, "rb").read() == open(b, "rb").read(), (
        f"vercel-app/{asset} is stale relative to ui/{asset}. "
        f"Run vercel-app/build.sh and commit the result.")


def test_stats_defines_venues_as_kitchens_not_raw_names():
    """Both twins must count folded, junk-filtered kitchen names.

    The bug this locks: stats() used terms aggs capped at 500 per field and
    reported 799 kitchens against 4,000+ real ones. A cap-based count cannot
    be allowed back in either file.
    """
    for path in (_UI_PATH, _VERCEL_PATH):
        src = ast.unparse(_functions(path)["stats"])
        assert "composite" in src or "_distinct_values" in src, (
            f"{path}: stats() no longer uses a truncation-free distinct count")
        assert '"size": 500' not in src and "'size': 500" not in src, (
            f"{path}: stats() reintroduced the truncated terms aggregation")
        assert "_is_junk_venue" in src, (
            f"{path}: stats() stopped filtering junk/chain venue names")
        assert "norm_venue" in src, (
            f"{path}: stats() stopped folding venue name variants")


def test_landing_static_numbers_are_placeholders_only():
    """The landing stats must be overwritten by /api/stats at runtime.

    The static values drifted (9,309 vs 9,312 live; pedigree 73 vs 65) and
    were presented as measurements. They are now kept as fallbacks, so this
    test asserts the live-updating hooks still exist rather than pinning
    numbers that will drift again.
    """
    html = open(os.path.join(_ROOT, "ui", "landing.html")).read()
    for id_ in ("n-edges", "n-people", "n-venues", "n-sources"):
        assert f'id="{id_}"' in html, f"landing lost the {id_} stat slot"
        assert f"getElementById('{id_}')" in html, (
            f"landing no longer rewrites #{id_} from /api/stats — "
            "the hardcoded value would be shown as fact")
