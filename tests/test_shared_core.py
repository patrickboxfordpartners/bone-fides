"""The shared web core: src/dossier.py and the two thin adapters around it.

ui/server.py (local demo) and vercel-app/api/search.py (Vercel function) used
to be hand-maintained copies of the same dossier logic, held together by an
AST parity test. They now both call src.dossier.dispatch(), so there is one
implementation. These tests keep it that way, and lock the behaviour the old
parity file protected.
"""
import ast
import importlib.util
import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from src import dossier  # noqa: E402

_DOSSIER_PATH = os.path.join(_ROOT, "src", "dossier.py")
_UI_PATH = os.path.join(_ROOT, "ui", "server.py")
_VERCEL_PATH = os.path.join(_ROOT, "vercel-app", "api", "search.py")
_BUILD = os.path.join(_ROOT, "vercel-app", "build.sh")


def _functions(path):
    tree = ast.parse(open(path).read())
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("path", [_UI_PATH, _VERCEL_PATH], ids=["ui/server.py", "vercel-app/api/search.py"])
def test_adapters_define_no_dossier_logic(path):
    """An adapter that grows its own copy of a dossier function is the old
    twin problem coming back. Adapters may only map HTTP onto dispatch()."""
    shared = set(_functions(_DOSSIER_PATH))
    copied = sorted(set(_functions(path)) & shared)
    assert not copied, f"{path} redefines dossier functions {copied}; call src.dossier instead"
    assert "dossier.dispatch(" in open(path).read(), f"{path} no longer routes /api/* through dispatch()"


def test_vercel_adapter_imports_from_a_checkout():
    """Without build.sh output the function falls back to src.dossier, so the
    module imports in tests and local tooling."""
    mod = _load("vercel_search_import", _VERCEL_PATH)
    assert mod.dossier.dispatch is not None
    assert hasattr(mod, "handler")


def test_build_ships_every_module_and_data_file_the_dossier_needs():
    """The function bundle has no src/ or ui/. Everything dossier imports
    (relative imports) or opens through data_path() must be copied into
    api/_lib/ by build.sh, or the deployed function fails at import or 404s."""
    build = open(_BUILD).read()
    code = open(_DOSSIER_PATH).read()
    modules = set(re.findall(r"^from \.(\w+) import", code, re.M))
    data = set(re.findall(r'data_path\("([^"]+)"\)', code))
    assert modules and data
    missing = [f"src/{m}.py" for m in sorted(modules | {"dossier"}) if f"{m}.py" not in build]
    missing += [f"ui/{d}" for d in sorted(data | {"venue_aliases.json"}) if d not in build]
    assert not missing, f"build.sh does not copy {missing} into api/_lib/"
    # each shipped module must itself stay self-contained
    for m in modules:
        text = open(os.path.join(_ROOT, "src", f"{m}.py")).read()
        assert not re.search(r"^\s*(from|import) src\b", text, re.M), f"src/{m}.py imports src.*, absent from the bundle"


def test_build_copies_every_page_the_rewrites_serve():
    """landing.html was once missing from the copy list, so the live homepage
    served a stale committed copy for weeks. Every page a rewrite targets
    must be copied from ui/."""
    import json
    rewrites = json.load(open(os.path.join(_ROOT, "vercel-app", "vercel.json")))["rewrites"]
    pages = {r["destination"].lstrip("/") for r in rewrites if r["destination"].endswith(".html")}
    build = open(_BUILD).read()
    assert pages and all(f"ui/{p}" in build for p in pages), f"build.sh must copy {sorted(pages)}"


def test_dispatch_routes_and_guards():
    class Down:
        def search(self, **kw):
            raise RuntimeError("index unreachable at https://secret-host")

    status, _, body = dossier.dispatch("/api/stats", "", "t1", client=lambda: Down())
    assert status == 500 and b"secret-host" not in body
    status, _, body = dossier.dispatch("/api/nope", "", "t1", client=lambda: Down())
    assert status == 404
    status, _, body = dossier.dispatch("/api/search", "q=", "t1", client=lambda: Down())
    assert status == 200 and b'"resolved": false' in body
    status, headers, body = dossier.dispatch("/api/map.js", "", "t1")
    assert status == 200 and body.startswith(b"window.MAPBOX_TOKEN = ")
    status, _, body = dossier.dispatch("/api/venues", "", "t1", client=lambda: Down())
    assert status == 200 and b'"venues"' in body


def test_dispatch_decodes_plus_encoded_facets():
    """URLSearchParams sends spaces as '+'. A partial query ("Finn Town") and
    a hood label must reach the query layer decoded, in both runtimes."""
    calls = []

    def fake_lineage(es, q, size=25, role=None, era=None, hood=None):
        calls.append({"q": q, "hood": hood})
        return []

    orig = dossier.lineage
    dossier.lineage = fake_lineage
    try:
        dossier.dispatch("/api/search", "q=Finn+Town&hood=Castro%2FUpper+Market", "t2", client=lambda: object())
    finally:
        dossier.lineage = orig
    assert calls[0] == {"q": "Finn Town", "hood": "Castro/Upper Market"}


def test_rate_limit_answers_429():
    for _ in range(5):
        dossier.dispatch("/api/tip", "", "t3", body_bytes=b'{"website": "bot"}', client=lambda: object())
    status, headers, _ = dossier.dispatch("/api/tip", "", "t3", body_bytes=b"{}", client=lambda: object())
    assert status == 429 and headers.get("Retry-After") == "60"


@pytest.mark.parametrize("path", [_DOSSIER_PATH, _UI_PATH, _VERCEL_PATH],
                         ids=["src/dossier.py", "ui/server.py", "vercel-app/api/search.py"])
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


def test_junk_filter_does_not_eat_real_restaurants():
    """Junk/chain matching must be whole-token, never substring.

    Substring matching dropped "Schubert's Bakery" and "Petite Auberge" from
    the kitchen count because both contain "uber". Whole-token matching keeps
    them while still rejecting the actual artefacts.
    """
    mod = dossier
    must_survive = ["Schubert's Bakery", "Petite Auberge", "Zuni Cafe",
                    "Tartine Bakery", "Chez Panisse", "Nopa",
                    "State Bird Provisions"]
    for name in must_survive:
        assert not mod._is_junk_venue(name), f"{name!r} wrongly dropped as junk"

    must_drop = ["Uber", "Google", "Google kitchen", "Starbucks",
                 "McDonald's", "Burger King Market St", "TBD", "null", "",
                 "Chipotle Mexican Grill", "Peet’s Coffee & Tea"]
    for name in must_drop:
        assert mod._is_junk_venue(name), f"{name!r} wrongly kept as a kitchen"


def test_stats_resolves_aliases_through_the_shared_identity():
    """stats() must count venue IDENTITIES, not spellings.

    This test used to lock the OPPOSITE: a docstring admitting that aliases
    were not resolved, because no identity table existed. One does now
    (ui/venue_aliases.json, applied by src.venue_aliases), and the index
    already stamps from_venue_key/to_venue_key — but nothing read them, so
    "Michael Mina" and "Restaurant Michael Mina" still counted as two
    restaurants despite the owner's ruling. A stamp no reader consumes is not
    a fix.

    Both traits are asserted together so the two halves cannot drift apart
    again: the docstring must say aliases ARE resolved, and the code must go
    through venue_key() rather than the legacy norm_venue().
    """
    for path in (_DOSSIER_PATH,):
        tree = ast.parse(open(path).read())
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "stats")
        doc = (ast.get_docstring(fn) or "").lower()
        assert "alias" in doc, (
            f"{path}: stats() docstring no longer says anything about aliases")
        assert "not resolve" not in doc, (
            f"{path}: stats() docstring still disclaims alias resolution, but "
            f"the corpus has an identity table and the count uses it now")
        src = ast.unparse(fn)
        assert "venue_key" in src, (
            f"{path}: stats() must count through venue_key(), the shared "
            f"identity the indexer stamped, not raw or lightly-normalized names")


def test_stats_result_is_cached():
    """stats() is memoized: every page load was re-scanning the corpus."""
    for path in (_DOSSIER_PATH,):
        src = ast.unparse(_functions(path)["stats"])
        assert "_STATS_CACHE" in src, (
            f"{path}: stats() lost its TTL cache, so every page load pays for "
            f"a full distinct-venue scan again")


def test_stats_defines_venues_as_kitchens_not_raw_names():
    """stats() must count folded, junk-filtered kitchen names.

    The bug this locks: stats() used terms aggs capped at 500 per field and
    reported 799 kitchens against 4,000+ real ones. A cap-based count cannot
    be allowed back.
    """
    for path in (_DOSSIER_PATH,):
        src = ast.unparse(_functions(path)["stats"])
        assert "composite" in src or "_distinct_values" in src, (
            f"{path}: stats() no longer uses a truncation-free distinct count")
        assert '"size": 500' not in src and "'size': 500" not in src, (
            f"{path}: stats() reintroduced the truncated terms aggregation")
        assert "_is_junk_venue" in src, (
            f"{path}: stats() stopped filtering junk/chain venue names")
        assert "venue_key" in src, (
            f"{path}: stats() stopped folding venue identities; norm_venue "
            f"alone leaves 'Michael Mina' and 'Restaurant Michael Mina' as "
            f"two kitchens")


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



def test_no_library_or_script_loads_the_local_server_for_its_logic():
    """ui/server.py is an adapter now. Offline tools that loaded it to reach
    dossier functions (venue_images, stamp_score_sample) broke silently when
    the logic moved; they must import src.dossier."""
    offenders = []
    for folder in ("src", "scripts"):
        for name in sorted(os.listdir(os.path.join(_ROOT, folder))):
            if name.endswith(".py"):
                text = open(os.path.join(_ROOT, folder, name)).read()
                if re.search(r'"ui",\s*"server\.py"|ui\.server\b|ui/server\.py"', text):
                    offenders.append(f"{folder}/{name}")
    assert not offenders, f"{offenders} load ui/server.py; import src.dossier instead"


def test_stamp_score_sample_entry_point(monkeypatch, tmp_path):
    mod = _load("stamp_score_sample_entry", os.path.join(_ROOT, "scripts", "stamp_score_sample.py"))
    import src.es
    monkeypatch.setattr(src.es, "make_client", lambda: object())
    monkeypatch.setattr(dossier, "measure_score_sample", lambda es: {"n": 1, "min": 5, "median": 5, "max": 5})
    out = tmp_path / "score_sample.json"
    monkeypatch.setattr(mod, "OUT", str(out))
    assert mod.main() == 0
    assert '"median": 5' in out.read_text()


def test_geocoder_writes_where_the_api_reads():
    """scripts/geocode.py moved out of ui/; its output must still land in the
    ui/venues_geo.json that dossier.venues_geo() and build.sh read."""
    text = open(os.path.join(_ROOT, "scripts", "geocode.py")).read()
    assert 'os.path.join(BASE, "ui", "venues_geo.json")' in text
    assert dossier.data_path("venues_geo.json") == os.path.join(_ROOT, "ui", "venues_geo.json")
