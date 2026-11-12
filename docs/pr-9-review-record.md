# PR review record — patrickboxfordpartners/bone-fides#9

**PR:** https://github.com/patrickboxfordpartners/bone-fides/pull/9
**Title:** Trust tier 1: honest corpus numbers, reconciled twins, guarded drift
**Branch:** `fix/trust-tier1` (merged 2026-11-12T17:49:03Z, merge commit `bd420b6d`, branch deleted)
**Final state:** MERGED

## Commits

| SHA | What |
|---|---|
| `b37bd53` | Tier 1: honest corpus numbers, reconciled twins, guarded drift |
| `b4e70c6` | Ignore `.vercel` — a stale project link at the repo root overrode `--scope` and sent deploys to the wrong team |
| `fed0275` | Greptile fixes: junk matcher ate real restaurants, counts, cost |

## Findings

Six inline findings from two bots. **All six were real** — zero false positives.

### Greptile (5, all P2, all fixed in `fed0275`)

| # | Finding | Verdict | Resolution |
|---|---|---|---|
| 1 | `_is_junk_venue` matched substrings, so "Schubert's Bakery" and "Petite Auberge" were dropped for containing "uber" | **Real** | Whole-token matching; chain phrases still match with branch suffixes. Count corrected 4,079 → **4,084** (the five restaurants the bug was eating) |
| 2 | `stats()` docstring promised "Tartine"/"Tartine Bakery" fold to one kitchen; `norm_venue` returns different strings | **Real** | Docstring rewritten to state aliases are NOT resolved; test locks the disclosure until a venue identity table exists |
| 3 | `/api/stats` rescanned the corpus on every page load | **Real** | composite page 1000 → 10000 (one round-trip per field); 300s per-instance TTL cache. Measured 1.68s cold → 0.000s warm |
| 4 | Landing said 4,079 kitchens in the headline but "Browse all 799 kitchens" and "2,219 articles" elsewhere | **Real** | Both prose counts got ids and are rewritten from the same `/api/stats` response |
| 5 | Asset test covered only app-root copies, missing `api/city_venues.json`, `api/venues_geo.json`, `api/_map.js` — the files the handler actually reads | **Real** | Test now tracks (source, destination) pairs including the api/ mirrors |

### testdriverai (1, minor, fixed in `fed0275`)

| # | Finding | Verdict | Resolution |
|---|---|---|---|
| 6 | ~10-12 sequential ES round-trips per `/api/stats`; no caching header or memo | **Real** (same root cause as Greptile #3) | Page size + TTL cache; same fix |

### Reviewers that did not run

- **CodeRabbit** — `SKIPPED`; repo has fewer than 10 stars so it does not auto-review.
- **tenki-reviewer** — "insufficient balance"; no review performed.
- **Vercel** / **Vercel Preview Comments** — both SUCCESS.

## Patterns worth carrying

1. **A trust fix introduced a new trust defect.** The Tier 1 junk filter was written with substring matching borrowed from `venues_geo`. In `venues_geo` the stakes are map dots; in `stats()` the same code silently deleted real restaurants from a headline number. Copying a filter into a counting role needs its own tests — which is exactly the class of bug this PR was supposed to eliminate.

2. **Docstrings that assert a behaviour are a liability.** The alias claim was written from intent, not from reading `norm_venue`. Greptile caught it by comparing the two. Any docstring claiming a fold/dedupe should have a test that fails if the claim becomes false.

3. **Deploy configuration had three compounding faults**, all invisible to tests: project Root Directory `vercel-app` meant deploying *from* that dir double-nested the path; a `.vercel/project.json` at the repo root pointed at a different project and silently overrode `--scope`; and `build.sh` never copied `landing.html`, so the deploy served a hand-maintained stale page. Deploys must run from the repo root.

4. **An alias outlives the deploy that set it.** After merging, `bone-fides.vercel.app` still served a pre-fix deployment pinned by a manual `vercel alias set`. Vercel's Git integration created the correct new production deployment but did not move the custom alias. Post-merge verification must check the *alias target*, not just that a deployment exists — production showed 4,079 while both recent deployments served 4,084.

## Verification at merge

- 185 tests pass (2 skipped)
- behavioural parity: both twins return identical dossiers across 8 query shapes
- live `https://bone-fides.vercel.app/api/stats` → `{"edges": 9312, "people": 3119, "venues": 4084, "sources": 2221}`
- landing renders 4,084 in all three places; pedigree 65
