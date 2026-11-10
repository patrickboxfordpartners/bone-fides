"""Roadmap 4.4 — era buckets from loose date strings.

The date field is a loose string ("2015", "January", "2008-2010",
"Dec. 23", "recently"). The &era= facet needs an index-time bucket stamp
the same way &role= needs role_bucket: a query param can't filter a text
field honestly.

Discipline (mirrors src/roles.py):
- No substring guessing. Only explicit patterns yield a year: bare
  4-digit years, years inside YYYY-MM-DD / YYYY-MM / YYYY-YYYY ranges, or
  a 4-digit year token with word boundaries ("opened in 2015",
  "fall 2017").
- Relative dates ("recently", "this summer", "end of the month") yield
  None — they carry no citable year, and the facet never lies.
- Ranges ("2008-2010") anchor on the FIRST year: for a career move, the
  arrival era is the honest single value, and decade grain makes the
  anchor choice era-equivalent for the 2-4 year spans the corpus holds.
- Years outside 1900-2026 are extraction noise, yield None.

era_bucket returns None (no stamp) or a bucket string.
"""

import re

# The era vocabulary. Decade buckets from 1990 on; pre-1990 catches the
# long tail (1931 Chez Panisse, 1980s edges). 2026 edges exist, so the
# 2020s bucket is open-ended.
ERA_BUCKETS = ("pre-1990", "1990s", "2000s", "2010s", "2020s")

_YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")


def _year(date_str):
    """First citable year in a loose date string, or None."""
    s = (date_str or "").strip()
    if not s:
        return None
    m = _YEAR_RE.search(s)
    if not m:
        return None
    y = int(m.group(0))
    if 1900 <= y <= 2026:
        return y
    return None


def era_bucket(date_str):
    """Loose date string -> era bucket, or None when no citable year."""
    y = _year(date_str)
    if y is None:
        return None
    if y < 1990:
        return "pre-1990"
    decade = (y // 10) * 10
    return f"{decade}s"


if __name__ == "__main__":
    for d in ("2015", "2009", "2010-2016", "1976-2015", "2006-12-31",
              "October 2017", "fall 2017", "January", "recently",
              "end of the month", "", None, "1045"):
        print(f"{d!r:20} -> {era_bucket(d)!r}")
