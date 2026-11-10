"""Role bucketing: raw role text -> dossier filter chips.

Locks the normalizer discipline (ROADMAP 4.1): token-based synonym fold,
never substring guessing, domain beats seniority. The corpus's 1,115 raw
values fold to {chef, executive chef, pastry, sous, owner, bartender, other}.
Three copies must agree: src/roles.py (canonical, used at index time) and
the two inline twins.
"""
import importlib.util
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.roles import role_bucket as src_bucket, BUCKETS  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SERVERS = [
    pytest.param(src_bucket, id="src/roles.py"),
    pytest.param(_load("ui_server", os.path.join(_HERE, "..", "ui", "server.py")).role_bucket,
                 id="ui/server.py"),
    pytest.param(_load("vercel_search", os.path.join(
        _HERE, "..", "vercel-app", "api", "search.py")).role_bucket,
                 id="vercel-app/api/search.py"),
]


@pytest.fixture(params=SERVERS)
def bucket(request):
    return request.param


def test_bucket_vocabulary_matches_twins():
    # the &role= facet accepts exactly the canonical vocabulary
    for mod_path in [os.path.join(_HERE, "..", "ui", "server.py"),
                     os.path.join(_HERE, "..", "vercel-app", "api", "search.py")]:
        assert set(_load("m_" + os.path.basename(mod_path), mod_path)._ROLE_BUCKETS) == set(BUCKETS)


def test_era_vocabulary_matches_twins():
    # roadmap 4.4: the &era= facet accepts exactly src.eras.ERA_BUCKETS
    from src.eras import ERA_BUCKETS
    expected = set(ERA_BUCKETS)
    for mod_path in [os.path.join(_HERE, "..", "ui", "server.py"),
                     os.path.join(_HERE, "..", "vercel-app", "api", "search.py")]:
        assert set(_load("e_" + os.path.basename(mod_path), mod_path)._ERA_BUCKETS) == expected


def test_hood_vocabulary_matches_twins():
    # roadmap 4.4: the &hood= facet accepts exactly the city file's
    # analysis_neighborhood labels (+ the curated closed-venue labels)
    from src.hoods import hood_vocabulary
    expected = set(hood_vocabulary())
    for mod_path in [os.path.join(_HERE, "..", "ui", "server.py"),
                     os.path.join(_HERE, "..", "vercel-app", "api", "search.py")]:
        assert set(_load("h_" + os.path.basename(mod_path), mod_path)._HOOD_VOCAB) == expected


def test_case_and_punctuation_fold(bucket):
    assert bucket("Chef") == bucket("chef")
    assert bucket("Executive Chef") == "executive chef"
    assert bucket("Chef/Owner") == "chef"
    assert bucket("chef-owner") == "chef"
    assert bucket("chef de cuisine") == "chef"


def test_domain_beats_seniority(bucket):
    # an executive pastry chef is pastry; an executive sous chef is sous
    assert bucket("executive pastry chef") == "pastry"
    assert bucket("Executive pastry chef") == "pastry"
    assert bucket("executive sous chef") == "sous"
    assert bucket("corporate chef") == "executive chef"
    assert bucket("co-executive chef") == "executive chef"


def test_ownership_reads_chef_first(bucket):
    # "chef and owner" cooks; "owner and chef" also cooks (chef token wins)
    assert bucket("chef and owner") == "chef"
    assert bucket("owner and chef") == "chef"
    assert bucket("chef-proprietor") == "chef"


def test_families(bucket):
    assert bucket("sous chef") == "sous"
    assert bucket("opening sous chef") == "sous"
    assert bucket("pastry chef") == "pastry"
    assert bucket("head baker") == "pastry"
    assert bucket("chef de partie") == "chef"
    assert bucket("line cook") == "chef"
    assert bucket("culinary director") == "chef"
    assert bucket("bartender") == "bartender"
    assert bucket("bar manager") == "bartender"
    assert bucket("restaurateur") == "owner"
    assert bucket("founder") == "owner"
    assert bucket("partner") == "owner"


def test_no_substring_guessing(bucket):
    # a bar manager is bar family; but a "chocolate martini" recipe mention
    # must not make anyone pastry, and a wine director is not a chef
    assert bucket("wine director") == "other"
    assert bucket("sommelier") == "other"
    assert bucket("general manager") == "other"
    assert bucket("waiter") == "other"
    assert bucket("dishwasher") == "other"
    assert bucket("CEO") == "other"


def test_junk_and_empty(bucket):
    # extraction noise stays other, never mis-files into a real bucket
    assert bucket("Michelin-starred resume inclusion") == "other"
    assert bucket("brain behind") == "other"
    assert bucket("Major Player") == "other"
    assert bucket("worked") == "other"
    assert bucket("") == "other"
    assert bucket(None) == "other"
