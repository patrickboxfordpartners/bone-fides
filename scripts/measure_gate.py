"""Measure, sample and label the citation display gate.

The gate (src/dossier.py citation_reason) decides which indexed moves the site
displays. This script is its measurement harness:

  --mine            count 1-3 word phrases of the moves that fail today's gate
                    because the quote holds no move cue; write the top 300 to
                    crawl/gate_review/phrases.json so candidate cue families can
                    be derived from the rejected set, not from imagination
  --report          for each cue family in dossier._CAREER_CUES, count the
                    newly accepted moves with and without the anchor rule
  --sample NAME     draw a labelled-sample file (see SAMPLES below) to
                    crawl/gate_review/<name>.json with empty label slots; the
                    draw is deterministic (smallest sha256 of seed+row id), so
                    the same corpus and seed give the same rows again
  --stamp           write tests/fixtures/gate_labels.json and ui/gate_stamp.json
                    from the labelled sample files and the current corpus
  --check           read the live index and confirm three facts: no move that
                    was displayed before is lost, the samples come again from
                    their seeds, and the counts equal the stamp

Edges are read from Elasticsearch (search_after pages of 5,000) or from a
cached file with --edges <path>, so mining and labelling need no credentials.

Run from the repo root:  .venv/bin/python scripts/measure_gate.py --mine
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src.cli import load_env  # noqa: E402

load_env(os.path.join(BASE, ".env"))

from src import dossier  # noqa: E402  (after load_env)

REVIEW = os.path.join(BASE, "crawl", "gate_review")
INDEX = "bone-fides-edges"


# ----------------------------------------------------------------- corpus I/O

def load_edges(path=None):
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    from src.es import make_client
    es = make_client()
    out, after = [], None
    while True:
        body = {"size": 5000, "query": {"match_all": {}}, "sort": [{"_doc": "asc"}]}
        if after is not None:
            body["search_after"] = after
        page = es.search(index=INDEX, body=body)["hits"]["hits"]
        if not page:
            break
        out.extend(h["_source"] for h in page)
        after = page[-1]["sort"]
    return out


def row_id(e):
    h = hashlib.sha256()
    for k in ("source_url", "person", "from_venue", "to_venue", "evidence"):
        h.update((e.get(k) or "").encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


# ------------------------------------------------------------------ old logic

def old_reason(e):
    """Today's gate outcome for one edge: 'move', 'promotion' or None.

    Kept as a local copy (not citation_reason) so --mine can run before any new
    cue exists and so the old path stays pinned: this function may only change
    when src/dossier.py's pattern hashes change.
    """
    ev = (e.get("evidence") or "").strip()
    if not ev:
        return None
    role = e.get("role") or ""
    if dossier._NONCAREER.search(role) or dossier._NONCAREER.search(ev):
        return None
    if (e.get("action") or "").upper() == "PROMOTED":
        return "promotion" if dossier._PROMO_CUE.search(ev) else None
    return "move" if dossier._MOVE_CUE.search(ev) else None


def no_cue_moves(edges):
    """The 5,479-ish group: rejected because the quote holds no move cue."""
    return [e for e in edges
            if old_reason(e) is None
            and (e.get("action") or "").upper() != "PROMOTED"
            and not dossier._NONCAREER.search(e.get("role") or "")
            and not dossier._NONCAREER.search(e.get("evidence") or "")
            and (e.get("evidence") or "").strip()]


def new_family(e):
    """Cue family that accepts a move today's gate rejects, or None."""
    return dossier.citation_reason(e) if hasattr(dossier, "citation_reason") else None


def newly_accepted(edges):
    return [e for e in edges if old_reason(e) is None and new_family(e)]


# --------------------------------------------------------------------- mining

_WORD = re.compile(r"[a-z][a-z'&]*")


def mine(edges, top=300):
    counts = {}
    for e in no_cue_moves(edges):
        ev = (e.get("evidence") or "").lower()
        words = _WORD.findall(ev)
        grams = set()
        for n in (1, 2, 3):
            for i in range(len(words) - n + 1):
                grams.add(" ".join(words[i:i + n]))
        for g in grams:
            counts[g] = counts.get(g, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return [{"phrase": p, "quotes": n} for p, n in ranked]


# ------------------------------------------------------------------- sampling

SAMPLES = {
    # name -> (population, seed, size)
    # "development" draws 40 rows for EACH candidate family and is for tuning;
    # "acceptance" proves the frozen patterns (the owner's 95% rule). Seed
    # acc-1 was the first draw: it measured 374/400 and its false rows drove
    # the named-person, named-kitchen and venue-kind guards. A sample that
    # changed a pattern cannot prove it, so the proving draw uses acc-2.
    # "baseline" measures the precision of the moves displayed today.
    "development": ("per_family", "dev-1", 40),
    "acceptance": ("newly_accepted", "acc-2", 400),
    "baseline": ("displayed_today", "base-1", 200),
}

# Round 1 of the acceptance measurement, kept for the fixture's "rounds"
# record: seed acc-1, the cue hash it was drawn under, its count, its result.
ROUND_ACC_1 = {"seed": "acc-1",
               "cue_hash": "3d24e740d31471f84bb4a027bdb7cfe0e2a62261fae8995573400f8752390f7b",
               "n": 400, "true": 374, "result": "fail"}


def _draw(rows, seed, n):
    keyed = sorted(
        (hashlib.sha256((seed + row_id(e)).encode()).hexdigest(), row_id(e), i, e)
        for i, e in enumerate(rows))
    out = []
    for _, rid, _, e in keyed[:n]:
        row = {"id": rid, "seed": seed, **e}
        fam = dossier.citation_reason(e)
        if fam and fam not in ("move", "promotion"):
            row["family"] = fam
        out.append(row)
    return out


def draw_sample(edges, name):
    kind, seed, n = SAMPLES[name]
    if kind == "per_family":
        rows = []
        for fam in sorted(dossier._CAREER_CUES):
            fam_rows = [e for e in edges if old_reason(e) is None
                        and new_family(e) == fam]
            rows.extend(_draw(fam_rows, f"{seed}-{fam}", n))
        return rows
    if kind == "newly_accepted":
        return _draw(newly_accepted(edges), seed, n)
    return _draw([e for e in edges if old_reason(e) is not None], seed, n)


# ------------------------------------------------------------------- stamping

def cue_hash():
    return dossier._cue_hash()


def old_pattern_hash():
    src = [dossier._MOVE_CUE.pattern, dossier._PROMO_CUE.pattern, dossier._NONCAREER.pattern]
    return hashlib.sha256("\n\n".join(src).encode()).hexdigest()


def _label_file(name):
    return os.path.join(REVIEW, f"{name}.json")


def _read_labels(name):
    path = _label_file(name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _counted_true(row):
    """The counting rule of the protocol, including adjudication.

    A row counts as true when both labellers said true. When the two
    labellers disagree (neither unsure), a third blind adjudicator that
    applied the plan's protocol text (docs/flagship/plan.md section 1.5)
    decides; its true resolves the dispute. 'unsure' counts as false.
    """
    if row.get("label") == "true" and row.get("second_label") == "true":
        return True
    if (row.get("label") != row.get("second_label")
            and "unsure" not in (row.get("label"), row.get("second_label"))
            and row.get("third_label") == "true"):
        return True
    return False


def _merged_sample(name):
    """Sample rows with both labellers' labels merged in.

    Labeller 1 (the build agent) writes mine_<name>.json; labeller 2 (blind,
    independent) writes second_<name>_*.json. Disagreements go to a third
    blind adjudicator (adjudication.json) that applies the plan's protocol
    text verbatim. Rows are ordered with the false and disputed rows first,
    so the owner reviews them before the rest.
    """
    rows = _read_labels(name)
    mine = {r["id"]: r for r in _read_labels(f"mine_{name}")}
    second = {}
    for path in sorted(os.listdir(REVIEW)):
        if path.startswith(f"second_{name}") and path.endswith(".json"):
            for r in _read_labels(path[:-5]):
                second[r["id"]] = r
    third = {r["id"]: r for r in _read_labels("adjudication")}
    out = []
    for r in rows:
        row = dict(r)
        m = mine.get(r["id"], {})
        s = second.get(r["id"], {})
        row["label"] = m.get("label")
        row["second_label"] = s.get("label")
        row["both"] = bool(m.get("both"))
        row["note"] = m.get("note") or s.get("note") or ""
        row["second_note"] = s.get("note") or ""
        if row["label"] is None or row["second_label"] is None:
            row["disputed"] = "unlabelled"
        elif "unsure" in (row["label"], row["second_label"]):
            row["disputed"] = "unsure"
        elif row["label"] != row["second_label"]:
            row["disputed"] = "adjudicated"
            t = third.get(r["id"])
            if t:
                row["third_label"] = t.get("label")
                row["third_note"] = t.get("note") or ""
        else:
            row["disputed"] = "no"
        row["counted_true"] = _counted_true(row)
        out.append(row)

    def _key(r):
        # false and disputed rows first, so the owner reviews them early
        disputed = 0 if r["disputed"] != "no" else 1
        false_first = 0 if not r["counted_true"] else 1
        return (disputed, false_first, r["id"])

    return sorted(out, key=_key)


def wilson_low(k, n, z=1.96):
    if not n:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return max(0.0, (c - h) / d)


def stamp(edges, measured_at=None):
    acceptance = _merged_sample("acceptance")
    baseline = _merged_sample("baseline")
    development = _read_labels("development")
    must_reject = _read_labels("must_reject")

    def true_share(rows):
        n = len(rows)
        k = sum(1 for r in rows if _counted_true(r))
        return n, k

    acc_n, acc_k = true_share(acceptance)
    base_n, base_k = true_share(baseline)

    by_family = {}
    for r in acceptance:
        fam = r.get("family") or "?"
        a, b = by_family.get(fam, (0, 0))
        by_family[fam] = [a + 1, b + (1 if _counted_true(r) else 0)]

    displayed_before = sum(1 for e in edges if old_reason(e) is not None)
    displayed = sum(1 for e in edges if dossier.citation_reason(e) is not None)

    stamp_obj = {
        "measured_at": measured_at or datetime.date.today().isoformat(),
        "on_record": len(edges),
        "displayed_before": displayed_before,
        "displayed": displayed,
        "newly_displayed": displayed - displayed_before,
        "sample_n": acc_n,
        "sample_true": acc_k,
        "precision": round(acc_k / acc_n, 4) if acc_n else 0.0,
        "precision_low": round(wilson_low(acc_k, acc_n), 4) if acc_n else 0.0,
        "both_share": (round(sum(1 for r in acceptance if r.get("both")) / acc_n, 4)
                      if acc_n else 0.0),
        "baseline_n": base_n,
        "baseline_true": base_k,
        "by_family": {k: v for k, v in sorted(by_family.items())},
        "cue_hash": cue_hash(),
    }

    labels = {
        "protocol": 1,
        "measured_at": stamp_obj["measured_at"],
        "cue_hash": cue_hash(),
        "old_pattern_hash": old_pattern_hash(),
        "corpus": {"on_record": stamp_obj["on_record"],
                   "displayed_before": stamp_obj["displayed_before"],
                   "displayed": stamp_obj["displayed"],
                   "newly_displayed": stamp_obj["newly_displayed"],
                   "lost": 0},
        "rounds": [ROUND_ACC_1,
                   {"seed": SAMPLES["acceptance"][1], "cue_hash": cue_hash(),
                    "n": acc_n, "true": acc_k,
                    "result": "pass" if acc_n and acc_k / acc_n >= 0.95 else "fail"}],
        "samples": {"acceptance": acceptance, "baseline": baseline,
                    "development": development, "must_reject": must_reject},
    }

    with open(os.path.join(BASE, "ui", "gate_stamp.json"), "w") as f:
        json.dump(stamp_obj, f, indent=1, sort_keys=True)
        f.write("\n")
    with open(os.path.join(BASE, "tests", "fixtures", "gate_labels.json"), "w") as f:
        json.dump(labels, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"stamp: displayed {displayed_before} -> {displayed} "
          f"(+{stamp_obj['newly_displayed']})")
    print(f"acceptance: {acc_k}/{acc_n} true = {stamp_obj['precision']}"
          f" (Wilson low {stamp_obj['precision_low']})")
    print(f"baseline: {base_k}/{base_n} true")
    for fam, (n, k) in sorted(by_family.items()):
        print(f"  {fam}: {k}/{n}")
    return stamp_obj


# ---------------------------------------------------------------------- check

def check(edges, verbose=True):
    ok = True
    stamp_obj = json.load(open(os.path.join(BASE, "ui", "gate_stamp.json"),
                               encoding="utf-8"))
    before = stamp_obj["displayed_before"]
    lost = [e for e in edges if old_reason(e) is not None
            and dossier.citation_reason(e) is None]
    if lost:
        ok = False
        print(f"FAIL: {len(lost)} displayed moves were lost")
    else:
        print("ok: no displayed move was lost")
    if stamp_obj["on_record"] != len(edges):
        ok = False
        print(f"FAIL: stamp says {stamp_obj['on_record']} moves on record, "
              f"index holds {len(edges)}")
    displayed = sum(1 for e in edges if dossier.citation_reason(e) is not None)
    if displayed != stamp_obj["displayed"]:
        ok = False
        print(f"FAIL: stamp says {stamp_obj['displayed']} displayed, "
              f"recount gives {displayed}")
    else:
        print(f"ok: displayed count {displayed} equals the stamp")
    # samples come again from their seeds
    for name in ("acceptance", "baseline"):
        rows = _read_labels(name)
        drawn = {r["id"] for r in draw_sample(edges, name)}
        if drawn == {r["id"] for r in rows}:
            print(f"ok: {name} sample comes again from its seed "
                  f"({len(rows)} rows)")
        else:
            ok = False
            print(f"FAIL: {name} sample does not come again from its seed")
    # cue hash
    if stamp_obj["cue_hash"] != cue_hash():
        ok = False
        print("FAIL: cue hash changed since the measurement")
    else:
        print("ok: cue hash equals the stamp")
    return 0 if ok else 1


# ------------------------------------------------------------------------ main

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--edges", help="cached edges file instead of Elasticsearch")
    p.add_argument("--mine", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--sample", choices=sorted(SAMPLES))
    p.add_argument("--stamp", action="store_true")
    p.add_argument("--check", action="store_true")
    a = p.parse_args(argv)

    edges = load_edges(a.edges)
    print(f"loaded {len(edges)} moves")

    os.makedirs(REVIEW, exist_ok=True)
    if a.mine:
        with open(os.path.join(REVIEW, "phrases.json"), "w") as f:
            json.dump(mine(edges), f, indent=1)
        print(f"wrote {REVIEW}/phrases.json")

    if a.report:
        if not hasattr(dossier, "citation_reason"):
            print("no _CAREER_CUES in dossier.py yet")
            return 1
        rows = no_cue_moves(edges)
        print(f"{len(rows)} no-cue moves")

        def raw_family(e):
            """Family whose PATTERN matches, before the anchor rule."""
            ev = (e.get("evidence") or "").strip()
            if dossier._NOT_A_STINT.search(ev):
                return None
            for fam, pat in dossier._CAREER_CUES.items():
                if fam == "credential":
                    if dossier._credential_lists_venue(e):
                        return fam
                elif pat.search(ev):
                    return fam
            return None

        with_anchor, raw = {}, {}
        for e in rows:
            fam = new_family(e)
            if fam:
                with_anchor[fam] = with_anchor.get(fam, 0) + 1
            else:
                fam = raw_family(e)
                if fam:
                    raw[fam] = raw.get(fam, 0) + 1
        total_a = 0
        for fam in sorted(dossier._CAREER_CUES):
            total_a += with_anchor.get(fam, 0)
            print(f"  {fam}: {raw.get(fam, 0) + with_anchor.get(fam, 0)} matches, "
                  f"{with_anchor.get(fam, 0)} with anchor")
        matched = sum(1 for e in rows if new_family(e))
        print(f"families accepted {matched} of {len(rows)} (anchor kept {total_a})")
        displayed_before = sum(1 for e in edges if old_reason(e) is not None)
        print(f"displayed: {displayed_before} -> {displayed_before + matched}")

    if a.sample:
        rows = draw_sample(edges, a.sample)
        path = _label_file(a.sample)
        if os.path.exists(path):
            old = {r["id"]: r for r in _read_labels(a.sample)}
            merged = []
            for r in rows:
                prev = old.get(r["id"])
                if prev is None:
                    merged.append(r)
                else:
                    prev = dict(prev)
                    prev.setdefault("family", r.get("family"))
                    prev.setdefault("source_url", r.get("source_url"))
                    merged.append(prev)
            rows = merged
        with open(path, "w") as f:
            json.dump(rows, f, indent=1, ensure_ascii=False)
        print(f"wrote {path} ({len(rows)} rows)")
        if a.sample == "development":
            fams = {}
            for r in rows:
                fams[dossier.citation_reason(r)] = fams.get(dossier.citation_reason(r), 0) + 1
            print("per family:", fams)

    if a.stamp:
        stamp(edges)

    if a.check:
        return check(edges)

    return 0


if __name__ == "__main__":
    sys.exit(main())
