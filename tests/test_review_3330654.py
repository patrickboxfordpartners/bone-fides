"""Regression tests for the post-ship review of commit 3330654.

Every critical finding from the two-reviewer pass, locked:
- plus-encoding facet params on the local twin (URLSearchParams sends
  spaces as '+', unquote_plus decodes them; plain unquote does not)
- CLOSED_SF lookups normalize (curly apostrophes, articles, case place
  the same as the straight curated key)
- out-of-city parenthetical annotations refuse the token-prefix fallback
- single-token permit keys never claim multi-token venue names
- completion edges carry facet stamps and get gated at the merge site
- the facet-empty probe forwards role and honors the citation gate
- twin find_edges copies stay in sync on gate composition
- era regex accepts decade-suffixed dates ("1970s") without lying about
  relative dates
"""
import importlib.util
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.eras import era_bucket  # noqa: E402
from src.hoods import hood_for, load_hood_maps  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_UI = _load("ui_server_rv", os.path.join(_ROOT, "ui", "server.py"))
_VERCEL = _load("vercel_search_rv", os.path.join(_ROOT, "vercel-app", "api", "search.py"))
_MAPS = load_hood_maps()


# Fix 1: + encoding on the local twin
def test_ui_server_parses_plus_encoded_facet_params():
    import re
    from urllib.parse import unquote_plus
    # mirror of the _search extraction lines, pinned by reading them
    src = open(os.path.join(_ROOT, "ui", "server.py")).read()
    assert "unquote_plus(mr.group(1))" in src, "role param must decode +"
    assert "unquote_plus(me.group(1))" in src, "era param must decode +"
    assert "unquote_plus(mh.group(1))" in src, "hood param must decode +"
    # and the decoding itself must actually fold + to space
    assert unquote_plus("South+of+Market") == "South of Market"


# Fix 2: CLOSED_SF normalized lookups
def test_closed_sf_curly_and_article_variants_place():
    cases = {
        "Masa's": "Nob Hill", "Masa’s": "Nob Hill",
        "Moose's": "Russian Hill", "Moose’s": "Russian Hill",
        "Slanted Door": "Financial District/South Beach",
        "The Slanted Door": "Financial District/South Beach",
        "The Fifth Floor": "Financial District/South Beach",
        "Plumpjack Cafe": "Marina", "PlumpJack Cafe": "Marina",
    }
    for name, expected in cases.items():
        assert hood_for(name, _MAPS) == expected, name


# Fix 3: out-of-city parentheticals refuse the prefix fallback
def test_out_of_city_parentheticals_stay_unstamped():
    for name in ("Tartine Manufactory (Los Angeles)",
                 "home-based business (East Oakland)",
                 "Alexander's Steakhouse (Cupertino)",
                 "Beit Rima (Daly City)",
                 "Asian Box (Palo Alto)"):
        assert hood_for(name, _MAPS) is None, name


# Fix 3b: single-token permit keys don't claim multi-token names
def test_single_token_permit_key_does_not_prefix_claim():
    # "Cache" (Inner Sunset permit row) must not grab Cache Creek Casino
    assert hood_for("Cache Creek Casino Resort", _MAPS) is None
    # real multi-token prefix matches still work
    assert hood_for("Tartine Bakery", _MAPS) == "Mission"


# Fix 5: completion edges carry stamps and get gated at the merge site
def test_completion_edges_carry_stamps_and_merge_site_gates():
    for mod in (_UI, _VERCEL):
        src = open(mod.__file__).read() if hasattr(mod, "__file__") else ""
    # stamps fetched by fetch_person_edges (both twins)
    for path in (os.path.join(_ROOT, "ui", "server.py"),
                 os.path.join(_ROOT, "vercel-app", "api", "search.py")):
        src = open(path).read()
        assert '"role_bucket", "era_bucket", "venue_hoods"' in src, path
        # merge site gates extras by the stamps
        assert 'e.get("role_bucket") == role' in src, path
        assert 'e.get("era_bucket") == era' in src, path
        assert 'hood in (e.get("venue_hoods") or [])' in src, path


def test_fetch_person_edges_returns_stamps():
    # live-shape check without ES: the function's source includes the
    # stamp fields and passes them through to the edge dict
    import inspect
    src = inspect.getsource(_UI.fetch_person_edges)
    assert "role_bucket" in src and "era_bucket" in src and "venue_hoods" in src
    src_v = inspect.getsource(_VERCEL.fetch_person_edges)
    assert "role_bucket" in src_v and "era_bucket" in src_v and "venue_hoods" in src_v


# Fix 6: role forwarded to the facet probe
def test_probe_forwards_role():
    for path in (os.path.join(_ROOT, "ui", "server.py"),
                 os.path.join(_ROOT, "vercel-app", "api", "search.py")):
        src = open(path).read()
        assert "_facet_probe(es, q, era=era, hood=hood, role=role)" in src, path


# Fix 7 + Greptile fix 4: the facet-empty claims rest on one shared honest
# probe — resolution, query-scoped rows, and the citation gate. Raw window
# matches (recipe rows, unrelated hits) prove nothing.
def test_facet_probes_are_scoped_and_citation_gated():
    for path, mod in ((os.path.join(_ROOT, "ui", "server.py"), _UI),
                      (os.path.join(_ROOT, "vercel-app", "api", "search.py"), _VERCEL)):
        src = open(path).read()
        # the shared ungated probe exists and binds rows to the query
        assert "def _cited_moves_exist(es, q):" in src, path
        assert "scope_edges(q, ungated, identity(ungated))" in src, path
        assert "[e for e in scoped if citation_supported(e)]" in src, path
        # the gated probe discriminates on RESOLUTION (a real dossier under
        # the gates), not on a raw gated hit
        probe = inspect.getsource(mod._facet_probe)
        assert "resolve_query(q, edges, identity(edges))" in probe, path
        # branch B requires BOTH probes before facet_empty=True
        assert "bool(probe) and bool(" in src, path


# Greptile fix 1: local twin decodes q with unquote_plus (URLSearchParams
# sends spaces in q as '+', so "Finn Town" must match "Finn Town Taproom")
def test_ui_server_q_decodes_plus():
    src = open(os.path.join(_ROOT, "ui", "server.py")).read()
    # both search and suggest
    assert src.count("urllib.parse.unquote_plus(m.group(1))") >= 2
    # and no plain-unquote q decoding is left
    assert "urllib.parse.unquote(m.group(1))" not in src


# Greptile fix 2: the backfill puts keyword mappings on BEFORE the first
# update (a mapping-less index would auto-create text fields and the term
# gates would silently match nothing)
def test_backfill_ensures_keyword_mappings_first():
    src = open(os.path.join(_ROOT, "src", "stamp_era_hoods.py")).read()
    assert "INDEX_SETTINGS" in src
    assert "put_mapping" in src
    # mapping check happens before the scan loop
    assert src.index("put_mapping") < src.index('for hit in scan(')


# Greptile fix 3: era regex refuses digit runs and attached words
def test_era_trailing_boundary():
    assert era_bucket("20150") is None
    assert era_bucket("2015ish") is None
    assert era_bucket("12345") is None
    # real forms still stamp
    assert era_bucket("2015") == "2010s"
    assert era_bucket("1970s") == "pre-1990"
    assert era_bucket("2022-10-04T23:47:38Z") == "2020s"


# Fix 10: twin find_edges gate composition stays in sync
def test_twin_find_edges_gate_strings_match():
    import inspect
    a = inspect.getsource(_UI.__dict__.get("find_edges") or _VERCEL.find_edges) \
        if hasattr(_UI, "find_edges") else None
    # ui/server.py imports find_edges from src.es; vercel carries the copy
    from src import es as src_es
    from src.es import find_edges as _src_fe
    import re
    def gates(source):
        return {l.strip() for l in source.splitlines()
                if "role_bucket" in l or "era_bucket" in l or "venue_hoods" in l
                or 'body["post_filter"]' in l}
    src_body = inspect.getsource(_src_fe)
    vercel_body = inspect.getsource(_VERCEL.find_edges)
    # the gate-composition lines must exist in both, modulo docstring
    for needle in ('{"term": {"role_bucket": role}}',
                   '{"term": {"era_bucket": era}}',
                   '{"term": {"venue_hoods": hood}}',
                   'body["post_filter"] = {"bool": {"filter": gates}}',
                   'body["post_filter"] = gates[0]'):
        assert needle in src_body, needle
        assert needle in vercel_body, needle


# Fix 9: era regex handles decade suffixes, never relative dates
def test_era_decade_suffixes_stamp():
    assert era_bucket("1970s") == "pre-1990"
    assert era_bucket("1980s") == "pre-1990"
    assert era_bucket("mid-1990s") == "1990s"
    assert era_bucket("late 1970s") == "pre-1990"
    assert era_bucket("1980s-1990s") == "pre-1990"


def test_era_relative_dates_stay_none():
    assert era_bucket("recently") is None
    assert era_bucket("this summer") is None
    assert era_bucket("1045s") is None  # out-of-window noise, even with s


# Fix 4: role facet chip clearable in both explorer twins
def test_explorer_facetclear_handles_role():
    for path in (os.path.join(_ROOT, "ui", "explorer.html"),
                 os.path.join(_ROOT, "vercel-app", "explorer.html")):
        src = open(path).read()
        assert "if(k === 'role'){ run({ role: null }); return; }" in src, path
        # role-chip re-render keeps era/hood disclosure chips
        assert "{ role: null, era: serverEra, hood: serverHood," in src, path


# Fix 8: facet-empty wording keyed off server-validated values
def test_facet_empty_wording_uses_validated_values():
    for path in (os.path.join(_ROOT, "ui", "explorer.html"),
                 os.path.join(_ROOT, "vercel-app", "explorer.html")):
        src = open(path).read()
        assert "const valEra = d.era_filter || null;" in src, path
        assert "const namedEra" in src, path


# Greptile fix 5: each filter names itself ONLY on its own server echo — no
# facet_empty fallback that blames era/hood when a different filter emptied
# the dossier (e.g. role=chef emptied it while era=bogus was rejected).
def test_facet_names_require_own_echo():
    for path in (os.path.join(_ROOT, "ui", "explorer.html"),
                 os.path.join(_ROOT, "vercel-app", "explorer.html")):
        src = open(path).read()
        assert "const namedRole = (valRole && serverRole === valRole) ? serverRole : null;" in src, path
        assert "const namedEra = (valEra && serverEra === valEra) ? serverEra : null;" in src, path
        assert "const namedHood = (valHood && serverHood === valHood) ? serverHood : null;" in src, path
        # the old facet_empty fallbacks are gone
        assert "!valEra && d.facet_empty === true" not in src, path
        assert "!valHood && d.facet_empty === true" not in src, path


# Greptile fix 6: coverage notes visible beside the chips, not hover-only
def test_facet_coverage_note_visible():
    for path in (os.path.join(_ROOT, "ui", "explorer.html"),
                 os.path.join(_ROOT, "vercel-app", "explorer.html")):
        src = open(path).read()
        assert "const facetNote = facetBits.filter(f => f.note).map(f => esc(f.note)).join(' · ');" in src, path
        assert '<span class="facetcov">${facetNote}</span>' in src, path
        assert ".rolebar .facetcov {" in src, path


# Fix 11 (found in browser verification): role-only facet-empty must not
# fall through to the plain resolve-fail message — the record HAS the name,
# the role filter emptied it. The branch gates on serverRole too, names it
# from the validated role_filter echo, and role carries no coverage caveat
# (it is stamped on every row).
def test_facet_empty_branch_gates_on_role():
    for path in (os.path.join(_ROOT, "ui", "explorer.html"),
                 os.path.join(_ROOT, "vercel-app", "explorer.html")):
        src = open(path).read()
        assert "if(serverRole || serverEra || serverHood){" in src, path
        assert "const valRole = d.role_filter || null;" in src, path
        assert "const namedRole = (valRole && serverRole === valRole) ? serverRole : null;" in src, path
        assert "if(namedRole) bits.push('role ' + esc(namedRole));" in src, path
        # coverage note only names facets actually in the message
        assert "const covNote = cov.length ? ' — ' + cov.join(', ') + '.' : '';" in src, path
