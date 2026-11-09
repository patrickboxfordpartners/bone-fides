"""Fix the one cross-person mis-extraction in the corpus (package D audit).

Doc F9ExqKEB0WJkFCNl2e4C has person=Bill Corbett but from_venue="Daniel
Patterson": the extractor read "After stints with Michael Mina and Daniel
Patterson, Corbett is taking his talents to the Absinthe group" and wrote
the employer-person into the venue field. The doc's real content — Corbett
joining the Absinthe group — is already covered by the sibling doc
"Michael Mina -> Absinthe group" from the same article, so nulling
from_venue loses nothing and keeps Absinthe represented.

Run once:
    set -a; source .env; set +a
    .venv/bin/python src/fix_patterson_venue.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from es import make_client, INDEX

DOC_ID = "F9ExqKEB0WJkFCNl2e4C"

def main():
    es = make_client()
    h = es.get(index="bone-fides-edges", id=DOC_ID)
    s = h["_source"]
    assert s["person"] == "Bill Corbett", f"unexpected person: {s['person']}"
    assert s.get("from_venue") == "Daniel Patterson", \
        f"doc already fixed or changed: from_venue={s.get('from_venue')}"
    es.update(index="bone-fides-edges", id=DOC_ID,
              body={"doc": {"from_venue": None, "venue_text": "Absinthe group"}},
              refresh=True)
    h2 = es.get(index="bone-fides-edges", id=DOC_ID)
    print("fixed:", {k: h2["_source"].get(k)
                     for k in ("person", "from_venue", "to_venue")})

if __name__ == "__main__":
    main()
