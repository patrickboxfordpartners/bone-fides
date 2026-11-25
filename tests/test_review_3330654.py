"""Regression tests for the post-ship review of commit 3330654.

Every critical finding from the two-reviewer pass, locked:
- CLOSED_SF lookups normalize (curly apostrophes, articles, case place
  the same as the straight curated key)
- out-of-city parenthetical annotations refuse the token-prefix fallback
- single-token permit keys never claim multi-token venue names
- completion edges carry facet stamps and get gated at the merge site
- the facet-empty probe forwards role and honors the citation gate
- find_edges composes facet gates as post_filter terms
- era regex accepts decade-suffixed dates ("1970s") without lying about
  relative dates
"""
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.eras import era_bucket  # noqa: E402
from src.hoods import hood_for, load_hood_maps  # noqa: E402


from src import dossier  # noqa: E402

_DOSSIER = os.path.join(_ROOT, "src", "dossier.py")
_MAPS = load_hood_maps()


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
    for path in (_DOSSIER,):
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
    src = inspect.getsource(dossier.fetch_person_edges)
    assert "role_bucket" in src and "era_bucket" in src and "venue_hoods" in src


# Fix 6: role forwarded to the facet probe
def test_probe_forwards_role():
    src = open(_DOSSIER).read()
    assert "_facet_probe(es, q, era=era, hood=hood, role=role)" in src


# Fix 7 + Greptile fix 4: the facet-empty claims rest on one shared honest
# probe — resolution, query-scoped rows, and the citation gate. Raw window
# matches (recipe rows, unrelated hits) prove nothing.
def test_facet_probes_are_scoped_and_citation_gated():
    for path, mod in ((_DOSSIER, dossier),):
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


# Greptile PR #8: the boundary is Unicode-aware — attached uppercase words,
# underscores, and non-ASCII letters are still attached words, and dates
# reach era_bucket without case normalization
def test_era_boundary_rejects_case_underscore_unicode():
    assert era_bucket("2015ISH") is None
    assert era_bucket("2015ISHES") is None
    assert era_bucket("2015_is") is None
    assert era_bucket("2015Éurope") is None
    assert era_bucket("2015à") is None
    assert era_bucket("2015日本") is None
    # punctuation-adjacent years stay valid (parens, brackets, hyphens)
    assert era_bucket("(2015)") == "2010s"
    assert era_bucket("[2017]") == "2010s"
    assert era_bucket("2017-fall") == "2010s"


# Fix 10: find_edges composes the facet gates as post_filter terms. There is
# one implementation now (src/es_query.py), used by the indexer and the API.
def test_find_edges_gate_strings():
    from src.es_query import find_edges
    body = inspect.getsource(find_edges)
    for needle in ('{"term": {"role_bucket": role}}',
                   '{"term": {"era_bucket": era}}',
                   '{"term": {"venue_hoods": hood}}',
                   'body["post_filter"] = {"bool": {"filter": gates}}',
                   'body["post_filter"] = gates[0]'):
        assert needle in body, needle
    from src import es
    assert es.find_edges is find_edges and dossier.find_edges is find_edges


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


# Fix 4: role facet chip clearable in the explorer
def test_explorer_facetclear_handles_role():
    for path in (os.path.join(_ROOT, "ui", "explorer.html"),):
        src = open(path).read()
        assert "if(k === 'role'){ run({ role: null }); return; }" in src, path
        # role-chip re-render keeps era/hood disclosure chips
        assert "{ role: null, era: serverEra, hood: serverHood," in src, path


# Fix 8: facet-empty wording keyed off server-validated values
def test_facet_empty_wording_uses_validated_values():
    for path in (os.path.join(_ROOT, "ui", "explorer.html"),):
        src = open(path).read()
        assert "const valEra = d.era_filter || null;" in src, path
        assert "const namedEra" in src, path


# Greptile fix 5: each filter names itself ONLY on its own server echo — no
# facet_empty fallback that blames era/hood when a different filter emptied
# the dossier (e.g. role=chef emptied it while era=bogus was rejected).
def test_facet_names_require_own_echo():
    for path in (os.path.join(_ROOT, "ui", "explorer.html"),):
        src = open(path).read()
        assert "const namedRole = (valRole && serverRole === valRole) ? serverRole : null;" in src, path
        assert "const namedEra = (valEra && serverEra === valEra) ? serverEra : null;" in src, path
        assert "const namedHood = (valHood && serverHood === valHood) ? serverHood : null;" in src, path
        # the old facet_empty fallbacks are gone
        assert "!valEra && d.facet_empty === true" not in src, path
        assert "!valHood && d.facet_empty === true" not in src, path


# Greptile fix 6: coverage notes visible beside the chips, not hover-only
def test_facet_coverage_note_visible():
    for path in (os.path.join(_ROOT, "ui", "explorer.html"),):
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
    for path in (os.path.join(_ROOT, "ui", "explorer.html"),):
        src = open(path).read()
        assert "if(serverRole || serverEra || serverHood){" in src, path
        assert "const valRole = d.role_filter || null;" in src, path
        assert "const namedRole = (valRole && serverRole === valRole) ? serverRole : null;" in src, path
        assert "if(namedRole) bits.push('role ' + esc(namedRole));" in src, path
        # coverage note only names facets actually in the message
        assert "const covNote = cov.length ? ' — ' + cov.join(', ') + '.' : '';" in src, path
