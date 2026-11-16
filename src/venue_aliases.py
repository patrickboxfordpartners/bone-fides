"""Apply the owner's venue-name adjudication (ui/venue_aliases.json).

The rules in venue_images.py fold FORMATTING (accents, quotes, a leading "The").
They cannot decide whether "Stars (San Francisco)" and "Stars (Seattle)" are one
restaurant — that is a fact about the world, not about spelling. So it is
recorded as data: a human read 95 groups and named the preferred title for each.

Three outcomes per name:
  merge      — every listed spelling IS the canonical title (Fifth Floor
               Restaurant -> Fifth Floor)
  location   — the name is one of several branches of a brand, and the CITY is
               part of the identity (Stars (Seattle) stays distinct from
               Stars (San Francisco)); each city keeps its own key
  otherwise  — unchanged

The file is authoritative. Nothing here guesses from name shape.
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALIASES = os.path.join(BASE, "ui", "venue_aliases.json")

_cache = None


def _load():
    global _cache
    if _cache is None:
        with open(ALIASES, encoding="utf-8") as f:
            data = json.load(f)
        table = {}
        for canonical, variants in (data.get("merge") or {}).items():
            for v in variants:
                table[_key(v)] = canonical
        _cache = {"alias": table, "data": data}
    return _cache


def _key(s):
    """Loose match key for looking a spelling up in the alias table.

    Must not depend on venue_images.norm/canonical_venue, because this module is
    imported BY venue_images; keeping it self-contained avoids a cycle.
    """
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-"))
    s = re.sub(r"[()]", " ", s)
    return re.sub(r"[^a-z0-9]", "", s.lower())


def preferred_title(name):
    """The owner's chosen title for this spelling, or the name unchanged."""
    return _load()["alias"].get(_key(name), name)


def is_location_variant(name):
    """True when this name belongs to a brand kept separate by city.

    Stars (Seattle) and Stars (San Francisco) are different identities, so the
    caller must NOT collapse them.
    """
    data = _load()["data"]
    locs = data.get("locations") or {}
    for brand, variants in locs.items():
        if name in variants:
            return True
    return False


def identity(name):
    """The key a venue should be counted and grouped under."""
    if is_location_variant(name):
        # keep the city: drop only the brand-level wrapping
        return _key(name)
    return _key(preferred_title(name))
