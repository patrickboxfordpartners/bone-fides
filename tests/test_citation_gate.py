"""The widened citation gate and its proof (docs/flagship/plan.md section 1).

Three things are locked here:

1. the gate itself — the owner's five examples pass, the must-reject kinds
   fail, the anchor rule has the whole-token discipline of _venue_touch;
2. the old path — its pattern sources are pinned by hash so nothing
   displayed before can be silently lost, and every baseline sample row
   still returns "move" or "promotion";
3. the proof — the labelled-sample precision is recomputed from
   tests/fixtures/gate_labels.json and must equal ui/gate_stamp.json, so a
   pattern edit with no new measurement fails the suite.
"""
import hashlib
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
from src import dossier, extract  # noqa: E402

FIXTURE = os.path.join(_HERE, "fixtures", "gate_labels.json")
STAMP = os.path.join(os.path.dirname(_HERE), "ui", "gate_stamp.json")

# sha256 of the pattern sources of _MOVE_CUE, _PROMO_CUE and _NONCAREER as
# they were before the widened gate (measured 2026-11-25, displayed = 3,388).
OLD_PATTERN_HASH = "bfae395d42ef21cb28cb349555d01b26dbb65a606d07d16915576f471835f68e"


def _edge(**kw):
    row = {
        "person": "Test Person", "from_venue": None, "to_venue": None,
        "role": "chef", "action": "JOINED", "confidence": "high",
        "evidence": "", "source": "eater",
        "source_url": "https://sf.eater.com/x",
    }
    row.update(kw)
    return row


def _old_reason(e):
    """Today's (pre-widening) gate outcome, reconstructed for the test."""
    ev = (e.get("evidence") or "").strip()
    if not ev:
        return None
    role = e.get("role") or ""
    if dossier._NONCAREER.search(role) or dossier._NONCAREER.search(ev):
        return None
    if (e.get("action") or "").upper() == "PROMOTED":
        return "promotion" if dossier._PROMO_CUE.search(ev) else None
    return "move" if dossier._MOVE_CUE.search(ev) else None


# ── 1. the owner's five examples, as real rows ──────────────────────────────

def test_owners_five_examples_pass():
    cases = [
        _edge(person="Corey Lee", role="chef-owner", action=None,
              from_venue="The French Laundry", to_venue="Benu",
              evidence="chef-owner -- and eight year veteran of the French Laundry -- Corey Lee"),
        _edge(person="Gregory Short", role="chef", action="JOINED",
              from_venue="French Laundry", to_venue="Masa's",
              evidence="Chef Gregory Short, the French Laundry vet who has been in the Masa's "
                       "kitchen since 2004..."),
        _edge(person="Rick Bruno", role="chef", action="JOINED",
              from_venue="Valhalla", to_venue="Rickey's",
              evidence="The chef is Rick Bruno, who was last at Valhalla in Sausalito."),
        _edge(person="Amanda Hoang", role="chef", action="JOINED",
              from_venue="Cyrus, The French Laundry", to_venue="Farmhouse Inn",
              evidence="Since 2023, husband-and-wife chefs with major Michelin cred - Craig "
                       "Wilmer (Petit Crenn, Coi) and Amanda Hoang (Cyrus, The French Laundry) - "
                       "have helmed the dining room..."),
        _edge(person="Anthony Secviar", role="chef", action=None,
              from_venue="The French Laundry", to_venue="Protégé",
              evidence="Protégé is from two French Laundry veterans, chef Anthony Secviar and "
                       "Master Sommelier Dennis Kelly."),
    ]
    for e in cases:
        assert dossier.citation_reason(e) is not None, e["evidence"][:60]


# ── 2. must-reject rows ─────────────────────────────────────────────────────

def _fixture():
    assert os.path.exists(FIXTURE), "tests/fixtures/gate_labels.json is missing"
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def test_every_must_reject_row_fails_the_gate():
    fx = _fixture()
    rows = fx["samples"]["must_reject"]
    assert rows, "no must_reject rows recorded"
    seen_kinds = set()
    for r in rows:
        seen_kinds.add(r["kind"])
        edge = _edge(person=r.get("person"), role=r.get("role"),
                     from_venue=r.get("from_venue"), to_venue=r.get("to_venue"),
                     action=r.get("action"), evidence=r.get("evidence"))
        assert dossier.citation_reason(edge) is None, (r["kind"], r.get("evidence", "")[:80])
    for kind in ("guest dinner", "pop-up collaboration", "supplier blurb",
                 "inspired by", "recipe sentence", "show or event as venue",
                 "promotion with no promotion word", "cue naming no row venue"):
        assert kind in seen_kinds, f"must_reject lacks a {kind!r} row"


# ── 3. the anchor rule ──────────────────────────────────────────────────────

def test_anchor_folds_accents():
    e = _edge(person="X Y", from_venue="Jardinière", to_venue="B",
              evidence="Ana Weinberg, formerly of Jardiniere, joins B")
    assert dossier.citation_reason(e) is not None


def test_anchor_never_crosses_a_token_boundary():
    # "El Faro" must not anchor "El Farolito": the whole point of keeping
    # word boundaries (the squashed identity once joined the two kitchens).
    e = _edge(person="X Y", from_venue="El Faro", to_venue=None,
              evidence="former El Farolito cook X Y is opening a taqueria")
    assert dossier._quote_names_venue(e) is False
    assert dossier.citation_reason(e) is None


def test_one_word_generic_venue_does_not_anchor():
    e = _edge(person="X Y", from_venue="Kitchen", to_venue=None,
              evidence="X Y, a veteran of this kitchen, pours the drinks")
    assert dossier._quote_names_venue(e) is False
    assert dossier.citation_reason(e) is None
    # a short real name still anchors ("Coi" names Coi)
    e2 = _edge(person="Alex Rivera", from_venue="Coi", to_venue=None,
               evidence="Alex Rivera, a veteran of Coi, pours the drinks")
    assert dossier._quote_names_venue(e2) is True
    assert dossier.citation_reason(e2) is not None


def test_new_cue_needs_a_person_reference():
    e = _edge(person="X Y", from_venue="Popson's", to_venue="Alba Ray's",
              evidence="the Cajun concept from the team behind Popson's")
    assert dossier.citation_reason(e) is None


def test_new_cue_rejects_a_contradicted_direction():
    e = _edge(person="Charlie Hallowell", from_venue=None,
              to_venue="Boot & Shoe Service",
              evidence="Hallowell stepped away from his businesses - Pizzaiolo, "
                       "Boot & Shoe Service, and Penrose")
    assert dossier.citation_reason(e) is None


def test_former_guard_rejects_a_vacant_space():
    # "former ... space/site/home/location" describes a room, not a stint;
    # the guard must not be defeated by the token run consuming the word
    for quote in ("The former Coco500 space will hold a new wine bar",
                  "a build-out of the former Little Skips home",
                  "in the former Mars bar site"):
        e = _edge(person="Alex Rivera", from_venue="Coco500", to_venue=None,
                  evidence=quote)
        assert dossier.citation_reason(e) is None, quote
    # a real tenure next to an incidental "space" phrase still passes
    e = _edge(person="David Kinch", from_venue="Manresa", to_venue=None,
              evidence="David Kinch, the former Manresa chef, is back")
    assert dossier.citation_reason(e) is not None


def test_partial_venue_name_anchors():
    # the quote names a shorter spelling of the row's venue: "Alfred's"
    # names "Alfred's Steakhouse" as a whole-token prefix
    e = _edge(person="Alex Rivera", from_venue="Alfred's Steakhouse", to_venue=None,
              evidence="Alex Rivera, former Alfred's sous chef, pours wine")
    assert dossier._quote_names_venue(e) is True
    assert dossier.citation_reason(e) is not None
    # the boundary rule still holds: no crossing into a longer word
    e2 = _edge(person="Alex Rivera", from_venue="El Farolito", to_venue=None,
               evidence="Alex Rivera, former El Faro cook, pours wine")
    assert dossier._quote_names_venue(e2) is False


def test_common_head_words_do_not_anchor():
    # a single common word is not a kitchen mention: "French" does not name
    # "French Laundry", and "Stars" cannot cross city branches
    e = _edge(person="Alex Rivera", from_venue="French Laundry", to_venue=None,
              evidence="A French chef, Alex Rivera is a veteran of Paris kitchens")
    assert dossier.citation_reason(e) is None

def test_stars_prefix_does_not_cross_branches():
    e = _edge(person="Alex Rivera", from_venue=None, to_venue="Stars (San Francisco)",
              evidence="Alex Rivera parted ways with Stars in Seattle")
    assert dossier.citation_reason(e) is None

def test_distinctive_head_words_still_anchor():
    e = _edge(person="Alex Rivera", from_venue="Alfred's Steakhouse", to_venue=None,
              evidence="Alex Rivera, former Alfred's sous chef, pours wine")
    assert dossier.citation_reason(e) is not None
    e2 = _edge(person="Jamie Lauren", from_venue=None, to_venue="Absinthe Brasserie and Bar",
               evidence="Jamie works as the Executive Chef at Absinthe")
    assert dossier.citation_reason(e2) is not None

def test_new_cue_rejects_a_show_as_venue():
    e = _edge(person="Mattin Noblia", from_venue="Top Chef", to_venue="Bento",
              evidence="prepared daily by a kitchen managed by Top Chef alum Mattin Noblia")
    assert dossier.citation_reason(e) is None


# ── 4. the old path is pinned ───────────────────────────────────────────────

def test_old_pattern_sources_are_pinned():
    src = "\n\n".join([dossier._MOVE_CUE.pattern, dossier._PROMO_CUE.pattern,
                       dossier._NONCAREER.pattern])
    assert hashlib.sha256(src.encode()).hexdigest() == OLD_PATTERN_HASH, (
        "_MOVE_CUE, _PROMO_CUE or _NONCAREER changed: moves displayed before "
        "the widened gate would not stay displayed. Restore the patterns or "
        "re-measure and update the fixture."
    )
    assert _fixture()["old_pattern_hash"] == OLD_PATTERN_HASH


def test_every_baseline_row_still_passes_the_old_path():
    fx = _fixture()
    rows = fx["samples"]["baseline"]
    assert len(rows) >= 200
    for r in rows:
        assert _old_reason(r) in ("move", "promotion"), r.get("evidence", "")[:80]
        assert dossier.citation_reason(r) in ("move", "promotion"), (
            r.get("evidence", "")[:80])


# ── 5. the proof is recomputed from the fixture ────────────────────────────

def _wilson_low(k, n, z=1.96):
    if not n:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return max(0.0, (c - h) / d)


def _counted_true(r):
    """The protocol's counting rule: both labellers true, or a disagreement
    (neither unsure) that a third blind adjudicator resolved as true.
    'unsure' counts as false."""
    if r.get("label") == "true" and r.get("second_label") == "true":
        return True
    if (r.get("label") != r.get("second_label")
            and "unsure" not in (r.get("label"), r.get("second_label"))
            and r.get("third_label") == "true"):
        return True
    return False


def test_acceptance_sample_meets_the_owners_rule():
    fx = _fixture()
    rows = fx["samples"]["acceptance"]
    assert len(rows) >= 400
    two_labels = all(r.get("label") and r.get("second_label") for r in rows)
    assert two_labels, "every acceptance row needs both labellers"
    true_rows = [r for r in rows if _counted_true(r)]
    precision = len(true_rows) / len(rows)
    assert precision >= 0.95, f"acceptance precision {precision:.3f} < 0.95"
    fams = {}
    for r in rows:
        fam = r.get("family")
        fams.setdefault(fam, [0, 0])
        fams[fam][0] += 1
        fams[fam][1] += 1 if _counted_true(r) else 0
    for fam, (n, k) in fams.items():
        if n >= 30:
            assert k / n >= 0.90, f"family {fam}: {k}/{n} < 0.90"
    # every adjudicated row keeps both raw labels plus the third label, so
    # the owner can see the disagreement, not just the verdict
    for r in rows:
        if r.get("third_label"):
            assert r["label"] != r["second_label"], r.get("person")


def test_every_acceptance_row_was_rejected_before_and_is_accepted_now():
    fx = _fixture()
    for r in fx["samples"]["acceptance"]:
        assert _old_reason(r) is None, r.get("evidence", "")[:80]
        assert dossier.citation_reason(r) == r.get("family"), (
            r.get("evidence", "")[:80])


def test_gate_stamp_equals_the_recomputed_figures():
    with open(STAMP, encoding="utf-8") as f:
        stamp = json.load(f)
    fx = _fixture()
    rows = fx["samples"]["acceptance"]
    base = fx["samples"]["baseline"]
    acc_true = sum(1 for r in rows if _counted_true(r))
    base_true = sum(1 for r in base if _counted_true(r))
    assert stamp["sample_n"] == len(rows)
    assert stamp["sample_true"] == acc_true
    assert abs(stamp["precision"] - round(acc_true / len(rows), 4)) < 1e-9
    z = 1.96
    p = acc_true / len(rows)
    d = 1 + z * z / len(rows)
    c = p + z * z / (2 * len(rows))
    h = z * ((p * (1 - p) + z * z / (4 * len(rows))) / len(rows)) ** 0.5
    assert abs(stamp["precision_low"] - round(max(0.0, (c - h) / d), 4)) < 1e-9
    by_family = {}
    for r in rows:
        fam = r.get("family") or "?"
        a, b = by_family.get(fam, (0, 0))
        by_family[fam] = [a + 1, b + (1 if _counted_true(r) else 0)]
    assert stamp["by_family"] == {k: v for k, v in sorted(by_family.items())}
    two_venue = [r for r in rows
                 if r.get("from_venue") and r.get("to_venue")]
    both = sum(1 for r in two_venue if r.get("both"))
    assert abs(stamp["both_share"] - round(both / max(1, len(two_venue)), 4)) < 1e-9
    assert stamp["baseline_n"] == len(base)
    assert stamp["baseline_true"] == base_true
    assert stamp["cue_hash"] == dossier._cue_hash()
    assert stamp["cue_hash"] == fx["cue_hash"]
    assert stamp["displayed"] >= stamp["displayed_before"]
    assert stamp["newly_displayed"] == stamp["displayed"] - stamp["displayed_before"]
    assert stamp["on_record"] == fx["corpus"]["on_record"]


# ── 6. ingestion and the method endpoint ────────────────────────────────────

def test_parse_extraction_admits_a_new_cue_row():
    raw = {"edges": [{
        "person": "Corey Lee", "from_venue": "The French Laundry", "to_venue": "Benu",
        "role": "chef-owner", "action": None, "mentor": None, "date": None,
        "evidence": "chef-owner -- and eight year veteran of the French Laundry -- Corey Lee",
        "confidence": "high",
    }]}
    rows = extract.parse_extraction(raw)
    assert len(rows) == 1


def test_parse_extraction_drops_a_guest_dinner_row():
    raw = {"edges": [{
        "person": "Christian Puglisi", "from_venue": "Restaurant RELÆ",
        "to_venue": "Bar Tartine", "role": "chef", "action": "JOINED",
        "mentor": None, "date": None,
        "evidence": "the guest chef appearance of Christian Puglisi of Restaurant RELÆ "
                    "(Denmark) at Bar Tartine",
        "confidence": "high",
    }]}
    assert extract.parse_extraction(raw) == []


def test_gate_stamp_reader():
    assert dossier.gate_stamp(_data_path=STAMP) == {
        k: v for k, v in json.load(open(STAMP, encoding="utf-8")).items()
        if k != "cue_hash"}
    assert dossier.gate_stamp(_data_path="/nonexistent/gate_stamp.json") is None


def test_method_returns_gate_from_the_stamp(monkeypatch):
    monkeypatch.setattr(dossier, "stats", lambda es: {
        "edges": 1, "people": 1, "venues": 1, "sources": 1})

    class _FakeES:
        def search(self, index=None, body=None):
            aggs = {f: {"doc_count": 0} for f in dossier._COVERAGE_FIELDS}
            aggs["tiers"] = {"buckets": []}
            if "aggs" in (body or {}):
                return {"aggregations": aggs}
            return {"hits": {"hits": []}}

    dossier._METHOD_CACHE["value"] = None
    value = dossier.method(_FakeES())
    assert value["gate"] == dossier.gate_stamp(_data_path=STAMP)
    assert "cue_hash" not in value["gate"]
