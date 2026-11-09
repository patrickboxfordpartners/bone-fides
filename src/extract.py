"""Mistral structured extraction: article prose -> lineage edges."""
import json, re

SCHEMA = {
    "type": "object",
    "properties": {
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "person": {"type": "string"},
                    "from_venue": {"type": ["string", "null"]},
                    "to_venue": {"type": ["string", "null"]},
                    "role": {"type": "string"},
                    "action": {"type": "string", "enum": ["JOINED", "DEPARTED", "PROMOTED", "OTHER"]},
                    "mentor": {"type": ["string", "null"]},
                    "date": {"type": ["string", "null"]},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["person", "from_venue", "role", "evidence", "confidence"],
            },
        }
    },
    "required": ["edges"],
}

SYSTEM = (
    "You extract chef-to-venue career lineage from food journalism. "
    "Every edge must be explicitly stated in the article. Never infer. "
    "person = the chef (by name). from_venue = where they came from (venue name, or null if unknown). "
    "to_venue = where they went (venue name, or null if unknown). "
    "role = their position. date = stated date range or null. "
    "action = the move type: JOINED (starting at to_venue), DEPARTED (leaving from_venue), "
    "PROMOTED (new title at same venue), OTHER. "
    "mentor = the named chef they worked under (e.g. 'sous chef under X'), or null. "
    "evidence = the exact phrase from the article supporting the edge. "
    "confidence = high if the article states it outright, medium if implied, low if speculative. "
    "Do not extract guest appearances, pop-ups, suppliers, or recipe sentences as career moves. "
    "action OTHER is only for a stated career fact that is not a join, departure, or promotion. "
    "If the article states no lineage, return an empty edges array."
)

FIELDS = "person, from_venue, to_venue, role, action, mentor, date, evidence, confidence"

def build_edges_prompt(article_text):
    return (
        f"{article_text}\n\nExtract every chef-venue lineage edge stated in this article "
        f"as JSON with fields: {FIELDS}. "
        "evidence is the source citation: the exact supporting phrase from the article. Only edges explicitly stated; never infer."
    )

def _norm_quote(s):
    s = (s or "").lower().replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", s).strip()

def evidence_in_article(evidence, article_text):
    """The quotation has to be a phrase the article actually contains."""
    ev = _norm_quote(evidence)
    if not ev:
        return False
    return ev in _norm_quote(article_text)

def parse_extraction(raw, article_text=None):
    """Validate model output.

    Drops edges with no person and venue, low confidence, empty evidence,
    guest/supplier roles, and promotions the quotation does not state.
    When article_text is given, evidence must appear in it.
    """
    # Imported lazily so this module stays usable without the UI server.
    from ui.server import citation_supported
    out = []
    for e in raw.get("edges", []):
        if not e.get("person") or not (e.get("from_venue") or e.get("to_venue")):
            continue
        if e.get("confidence") == "low":
            continue
        evidence = (e.get("evidence") or "").strip()
        if not evidence:
            continue
        role = (e.get("role") or "").strip()
        action = e.get("action") or "OTHER"
        row = {
            "person": e["person"].strip(),
            "from_venue": (e.get("from_venue") or "").strip() or None,
            "to_venue": (e.get("to_venue") or "").strip() or None,
            "role": role,
            "action": action,
            "mentor": (e.get("mentor") or "").strip() or None,
            "date": e.get("date"),
            "evidence": evidence,
            "confidence": e.get("confidence"),
        }
        if not citation_supported(row):
            continue
        if article_text is not None and not evidence_in_article(evidence, article_text):
            continue
        out.append(row)
    return out

def extract_edges(client, article_text, model="mistral-large-latest"):
    """Call Mistral chat with structured output; returns validated edge list."""
    resp = client.chat.complete(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": build_edges_prompt(article_text)},
        ],
        response_format={"type": "json_schema", "json_schema": {"name": "edges", "schema": SCHEMA, "strict": True}},
    )
    return parse_extraction(json.loads(resp.choices[0].message.content), article_text=article_text)
