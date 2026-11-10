"""Roadmap 4.4 — venue -> neighborhood enrichment.

The city permit snapshot (ui/city_venues.json, from SF DPH inspections,
pulled by src/pull_city.py) carries an analysis_neighborhood on 99% of
its 8,155 rows — but only for businesses with an ACTIVE permit file. The
corpus's most-cited kitchens include closed venues (Betelnut, SPQR, Bar
Agricole, Rubicon) that no longer appear there, and non-SF venues
(Manresa, Chez Panisse, French Laundry) that must NOT get an SF hood.

So the join is: city-file flagship row per lineage name (the same row the
map pins), majority-vote fallback over the raw permit rows, an
unambiguous token-boundary prefix fallback, and a small curated map for
closed SF kitchens the permit file can't see. tag_city.norm normalizes
both sides (case, quotes, article, punctuation) — imported, not
re-typed, so the two joins can never drift.

Nothing here claims a venue is SF. A venue the maps can't place stays
unstamped; the facet discloses partial coverage.
"""

import collections
import json
import os
import re

from src.tag_city import norm

# "(Los Angeles)", "(East Oakland)", "(as a pop-up)": parenthetical
# annotations. When one names a place outside SF, the token-prefix
# fallback must not stamp the SF head venue's hood on the branch.
_PAREN_RE = re.compile(r"\(([^)]*)\)")
_NONCITY_HINTS = ("los angeles", "oakland", "daly city", "cupertino",
                  "palo alto", "berkeley", "san jose", "sacramento",
                  "portland", "seattle", "new york", "yonkers",
                  "st. helena", "healdsburg", "sonoma", "napa")

def _norm(s):
    """tag_city.norm with curly quotes straightened first.

    The corpus spells names with U+2019 (Mister Jiu's) while the permit
    file uses straight apostrophes, and tag_city.norm's fold class predates
    the curly variants — straightening here keeps ONE normalizer on both
    sides of the join."""
    s = (s or "").replace("’", "'").replace("‘", "'")
    return norm(s)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CITY = os.path.join(_BASE, "ui", "city_venues.json")

# Kitchens with a real lineage footprint that the permit snapshot cannot
# see — closed venues (Betelnut, SPQR, Rubicon, ...) AND open ones whose
# DBA is missing from the DPH file (Frances, Town Hall, Slanted Door:
# all open, all absent from the 8,155-row snapshot). Every hood below was
# verified against the city file's own analysis_neighborhood for nearby
# rows on the same street block (±100 street numbers, majority vote),
# NOT guessed from local knowledge. Labels use the city vocabulary.
# Unverifiable-by-block venues stay out (Bar Agricole 355 11th, Munchery
# and Charles Nob Hill ARE verified below via street-level context).
CLOSED_SF = {
    # (keys are curated display spellings; lookups go through _norm so
    # case/curly-apostrophe/article variants place the same — see
    # closed_sf_norm below)
    "Aqua": "Financial District/South Beach",        # 252 California
    "Ame": "Financial District/South Beach",         # 689 Mission
    "AQ": "South of Market",                         # 1155 Mission
    "Bacar": "South of Market",                      # 268 4th
    "Bar Agricole": "South of Market",               # 355 11th
    "Bar Tartine": "Mission Bay",                    # 561 Division (city's analysis area)
    "Betelnut": "Marina",                            # 2030 Union
    "Bluestem Brasserie": "Financial District/South Beach",  # 1 Yerba Buena Ln
    "Campton Place": "Financial District/South Beach",       # 340 Stockton
    "Central Kitchen": "Mission",                    # 3000 20th
    "Charles Nob Hill": "Nob Hill",                  # 1450 Sacramento (Huntington block)
    "Cortez": "Western Addition",                    # 540 Van Ness
    "Elisabeth Daniel": "Financial District/South Beach",    # 340 Bush
    "Elite Cafe": "Pacific Heights",                 # 2049 Fillmore
    "Fifth Floor": "Financial District/South Beach", # 12 4th (Palomar block)
    "Frances": "Castro/Upper Market",                # 3871 18th
    "Fringale": "South of Market",                   # 590 4th
    "Gitane": "Nob Hill",                            # 675 Post
    "Grand Cafe": "Western Addition",                # 601 Van Ness
    "Hawthorne Lane": "Financial District/South Beach",      # 22 Hawthorne
    "Hutong": "Marina",                              # 2030 Union (Betelnut's room)
    "Incanto": "Noe Valley",                         # 1550 Church
    "Jardinière": "Tenderloin",                      # 700 Van Ness
    "Jardiniere": "Tenderloin",
    "La Folie": "Russian Hill",                      # 2316 Polk
    "Locanda": "Mission",                            # 557 Valencia
    "Masa's": "Nob Hill",                            # 632 Bush
    "Maven": "Hayes Valley",                         # 598 Haight
    "Mecca": "Castro/Upper Market",                  # 2025 Market
    "Michael Mina": "Financial District/South Beach",        # 252 Stockton
    "Moose's": "Russian Hill",                       # 925 North Point
    "Mourad": "Financial District/South Beach",      # 140 New Montgomery
    "Munchery": "South of Market",                   # 800 5th
    "Nombe": "Mission",                              # 2491 Mission
    "Noosh": "South of Market",                      # 385 8th
    "Parallel 37": "Financial District/South Beach", # 600 Stockton
    "Penrose": "South of Market",                    # 1123 Folsom
    "PlumpJack Cafe": "Marina",                      # 3127 Fillmore
    "Postrio": "Hayes Valley",                       # 522 Hayes
    "Range": "Mission",                              # 842 Valencia
    "Redwood Park": "Nob Hill",                      # 950 Mason (Fairmont)
    "Rubicon": "Chinatown",                          # 558 Sacramento (city block label)
    "Slanted Door": "Financial District/South Beach",        # 1 Ferry Building
    "SPQR": "Pacific Heights",                       # 1911 Fillmore
    "Town Hall": "Financial District/South Beach",   # 344 Howard
    "Ubuntu": "Chinatown",                           # 595 Broadway (city block label)
}


def hood_vocabulary(city_path=None):
    """Every hood label the stamps can carry, sorted — the vocabulary the
    &hood= facet accepts (both twins mirror it inline)."""
    cv = json.load(open(city_path or _CITY))["venues"]
    labels = {v.get("neighborhood") for v in cv
              if v.get("neighborhood")} | set(CLOSED_SF.values())
    return tuple(sorted(labels))


def load_hood_maps(city_path=None):
    """Build the lookup maps from the city file once.

    Returns (lin_hood, permit_hood, closed_sf_norm):
    - lin_hood: norm(lineage_name) -> hood of that kitchen's flagship row
      (shortest row name per lineage — the row the map pins).
    - permit_hood: norm(permit name) -> majority-vote hood across the rows
      sharing that key.
    - closed_sf_norm: _norm(curated spelling) -> hood, so a corpus
      spelling like 'Masa’s' (curly) or 'The Slanted Door' places the
      same as the straight curated key.
    """
    cv = json.load(open(city_path or _CITY))["venues"]
    rows = {}
    for v in cv:
        ln = v.get("lineage_name")
        nb = v.get("neighborhood")
        if ln and nb:
            k = _norm(ln)
            if k not in rows or len(v["name"]) < rows[k][1]:
                rows[k] = (nb, len(v["name"]))
    lin_hood = {k: hood for k, (hood, _) in rows.items()}
    counts = {}
    for v in cv:
        nb = v.get("neighborhood")
        if not nb:
            continue
        k = _norm(v["name"])
        counts.setdefault(k, collections.Counter())[nb] += 1
    permit_hood = {k: c.most_common(1)[0][0] for k, c in counts.items()}
    closed_sf_norm = {_norm(k): hood for k, hood in CLOSED_SF.items()}
    return lin_hood, permit_hood, closed_sf_norm


def hood_for(name, maps=None):
    """Venue name -> neighborhood, or None when it can't be placed.

    Order: lineage flagship row, exact permit row, unambiguous
    token-prefix (len>=4 both sides), curated closed-venue map. Non-SF
    venues stay unstamped — nothing invents an SF hood for Chez Panisse.
    """
    lin_hood, permit_hood, closed_sf_norm = (
        maps if maps is not None else load_hood_maps())
    k = _norm(name or "")
    if not k:
        return None
    if k in lin_hood:
        return lin_hood[k]
    if k in permit_hood:
        return permit_hood[k]
    # token-boundary prefix fallback, len>=4 both sides, must be
    # unambiguous (the raw-substring bug tag_city's docstring warns
    # about: "All Washed Up" must not grab "(Washbag)"). A parenthetical
    # annotation naming another city ("(Los Angeles)", "(Daly City)")
    # marks an out-of-city branch — norm flattens those to trailing
    # tokens that must never tip the prefix match; such venues only
    # place via the curated map.
    if len(k) >= 4:
        for m in _PAREN_RE.finditer(name or ""):
            hint = m.group(1).strip().lower()
            if hint and any(c in hint for c in _NONCITY_HINTS):
                return closed_sf_norm.get(k)
        cands = set()
        for pk, hood in permit_hood.items():
            if len(pk) < 4:
                continue
            # the shorter key must end at a token boundary of the longer
            # one AND be multi-token itself: a single-token permit key
            # ("Cache") is a word match, not a name prefix — it must not
            # claim "Cache Creek Casino Resort" (a different business).
            if " " not in pk:
                continue
            if k.startswith(pk + " ") or pk.startswith(k + " "):
                cands.add(hood)
        if len(cands) == 1:
            return next(iter(cands))
    return closed_sf_norm.get(k)
