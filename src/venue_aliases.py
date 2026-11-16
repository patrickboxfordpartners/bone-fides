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

_HERE = os.path.dirname(os.path.abspath(__file__))

# The table lives in TWO layouts and this file ships to both:
#   repo checkout : <root>/src/venue_aliases.py   -> <root>/ui/venue_aliases.json
#   Vercel bundle : <fn>/venue_aliases.py         -> <fn>/venue_aliases.json
# build.sh copies both files side by side into api/. Trying the sibling first
# costs nothing and is the only one that works in the bundle; the repo path is
# the fallback so local runs are unchanged.
ALIASES = next(
    (p for p in (
        os.path.join(_HERE, "venue_aliases.json"),
        os.path.join(os.path.dirname(_HERE), "ui", "venue_aliases.json"),
    ) if os.path.exists(p)),
    os.path.join(os.path.dirname(_HERE), "ui", "venue_aliases.json"),
)

_cache = None


def _load():
    global _cache
    if _cache is None:
        with open(ALIASES, encoding="utf-8") as f:
            data = json.load(f)
        table, table_words = {}, {}
        for canonical, variants in (data.get("merge") or {}).items():
            # Table keys go through the SAME fold as lookups — including the
            # leading-article rule. Keying them raw meant a ruling written for
            # "The Mandarin restaurant" was stored under "themandarinrestaurant"
            # while the lookup asked for "mandarinrestaurant", so the ruling
            # silently stopped applying and the venue split again.
            title = base_identity(canonical)
            words = _fold_words(canonical)
            for v in list(variants) + [canonical]:
                k = base_identity(v)
                table[k] = title
                table_words[k] = words
        _cache = {"alias": table, "alias_words": table_words, "data": data}
    return _cache


def _fold(name):
    """Accent-fold, normalize quotes and dashes, then squash to [a-z0-9].

    A parenthetical STREET ADDRESS is dropped outright: "Saison (2124 Folsom
    St.)" is the same restaurant as "Saison". Keeping the address made each
    such spelling its own identity, which inflated the distinct count.
    """
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-"))
    s = re.sub(r"\(\s*\d[^)]*\)", " ", s)
    return re.sub(r"[^a-z0-9]", "", re.sub(r"[()]", " ", s).lower())


def _fold_words(name):
    """Same fold as _fold — INCLUDING the leading-article rule — but keeps
    spaces between words.

    The squashed form is the storage key. It is lossy in exactly one way that
    matters: word boundaries disappear, so "elfaro" is a character prefix of
    "elfarolito" and two different restaurants look like one. Dossier matching
    needs the boundaries, so it uses this form.

    The article must be stripped here too. It was not, so `identity('The
    Progress')` and `identity('Progress')` returned one key while the matching
    form returned "the progress" and "progress" — which fail the whole-word
    comparison, splitting one career across two dossier cards.
    """
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-"))
    s = re.sub(r"\(\s*\d[^)]*\)", " ", s)
    s = re.sub(r"[()]", " ", s).lower()
    words = re.sub(r"[^a-z0-9\s]", " ", s).split()
    # leading whole word "the", only when something follows it
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return " ".join(words)


def base_identity(name):
    """Formatting + leading whole-word "The", with no human adjudication.

    Deliberately a local copy of venue_images.venue_identity rather than an
    import. This module has to run in BOTH runtimes — the local server and the
    Vercel function — and the Vercel bundle contains no `src/` package, so an
    `import src.venue_images` there would 500 the stats endpoint. Keeping it
    stdlib-only is what lets the same file be copied into that bundle.

    tests/test_venue_images.py asserts this stays identical to
    venue_images.venue_identity, so the copy cannot silently drift.
    """
    import re

    k = _fold(name)
    if re.match(r"^\s*the\b\s*\S", (name or ""), re.I) and len(k) > 6:
        return _fold(re.sub(r"^\s*the\b\s*", "", name, flags=re.I))
    return k


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
    """The owner's chosen title for this spelling, or the name unchanged.

    Lookup uses base_identity, the same fold the table was keyed with, so the
    article form and the plain form of a name find the SAME ruling.
    """
    return _load()["alias"].get(base_identity(name), name)


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
    """The key a venue should be counted and grouped under.

    Layered, in this order, because each layer answers a different question:

      1. formatting (accents, quotes, dashes, parens) and a leading whole-word
         "The" — via venue_images.venue_identity. These are spelling facts.
      2. the human rulings in ui/venue_aliases.json — facts about the world.

    Applying only (2), which is what this did first, left "The French Laundry"
    and "French Laundry" as separate keys: the table lists "French Laundry"
    but not the article form, so the formatting rule never ran. The table is a
    set of exceptions to a general rule, not a replacement for it.

    Location variants are the exception: their city is part of the identity, so
    the brand-level "The" is still folded but the city qualifier is kept.
    """
    if is_location_variant(name):
        # keep the city: fold only the brand-level wrapper
        return _key(name)
    # base_identity of the resolved title, so every spelling of one ruling
    # lands on exactly one key. The table stores base_identity(canonical) as
    # its value, so this is a no-op on the title and the whole path is stable.
    return base_identity(preferred_title(base_identity(name)))


def identity_words(name):
    """identity(), but with spaces kept between words.

    For dossier matching, which needs word boundaries: the squashed identity
    makes "elfaro" a prefix of "elfarolito", joining El Faro and El Farolito
    into one career history. Same folding and same rulings as identity() — only
    the separator differs, so a name that matches here matches there.
    """
    if is_location_variant(name):
        return _fold_words(name)
    k = base_identity(name)
    data = _load()
    if k in data["alias_words"]:
        return data["alias_words"][k]
    return _fold_words(name)
