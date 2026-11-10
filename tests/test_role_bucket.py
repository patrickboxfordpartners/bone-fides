"""Role bucketing: raw role text -> dossier filter chips.

Locks the normalizer discipline (ROADMAP 4.1): token-based synonym fold,
never substring guessing, domain beats seniority. The corpus's 1,115 raw
values fold to {chef, executive chef, pastry, sous, owner, bartender, other}.
"""
import importlib.util
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SERVERS = [
    pytest.param(_load("ui_server", os.path.join(_HERE, "..", "ui", "server.py")),
                 id="ui/server.py"),
    pytest.param(_load("vercel_search", os.path.join(
        _HERE, "..", "vercel-app", "api", "search.py")), id="vercel-app/api/search.py"),
]


@pytest.fixture(params=SERVERS)
def bucket(request):
    return request.param.role_bucket


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
