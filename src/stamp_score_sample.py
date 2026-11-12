"""Measure the lineage-score distribution the /method page publishes.

The page states a range and median for a fixed sample of well-documented
kitchens. Computing that live costs ~7s (18 dossier assemblies) on every cold
serverless instance, which is too slow for a page whose entire job is to be
trustworthy the moment it loads. So it is measured here, written to a small
JSON file, and shipped with the deploy.

Re-run after a corpus-growth session so the published distribution tracks the
data:

    ./.venv/bin/python src/stamp_score_sample.py

The output records when it was measured, so the page can say so rather than
implying the number is live to the second.
"""
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src.cli import load_env  # noqa: E402

load_env(os.path.join(BASE, ".env"))

OUT = os.path.join(BASE, "ui", "score_sample.json")


def main():
    # Imported inside main so load_env runs first (the server module reads
    # ELASTIC_* at import time).
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ui_server_sample", os.path.join(BASE, "ui", "server.py"))
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    from src.es import make_client

    es = make_client()
    # measure_score_sample() computes; _score_sample() only reads the file.
    # Calling the reader here passed an ES client into open() — TypeError.
    sample = ui.measure_score_sample(es)
    if not sample:
        print("no scores computed — corpus unreachable or sample empty")
        return 1

    payload = dict(sample)
    payload["measured_at"] = datetime.date.today().isoformat()
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"wrote {OUT}: {payload}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
