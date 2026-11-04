"""Mistral structured extraction: article prose -> lineage edges."""
import json

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
    "If the article states no lineage, return an empty edges array."
)

FIELDS = "person, from_venue, to_venue, role, action, mentor, date, evidence, confidence"

def build_edges_prompt(article_text):
    return (
        f"{article_text}\n\nExtract every chef-venue lineage edge stated in this article "
        f"as JSON with fields: {FIELDS}. "
        "evidence is the source citation: the exact supporting phrase from the article. Only edges explicitly stated; never infer."
    )

def parse_extraction(raw):
    """Validate + filter model output: drop edges without person+venue or low confidence."""
    out = []
    for e in raw.get("edges", []):
        if not e.get("person") or not (e.get("from_venue") or e.get("to_venue")):
            continue
        if e.get("confidence") == "low":
            continue
        out.append({
            "person": e["person"].strip(),
            "from_venue": (e.get("from_venue") or "").strip() or None,
            "to_venue": (e.get("to_venue") or "").strip() or None,
            "role": e.get("role", "").strip(),
            "action": e.get("action") or "OTHER",
            "mentor": (e.get("mentor") or "").strip() or None,
            "date": e.get("date"),
            "evidence": e.get("evidence", "").strip(),
            "confidence": e.get("confidence"),
        })
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
    return parse_extraction(json.loads(resp.choices[0].message.content))
