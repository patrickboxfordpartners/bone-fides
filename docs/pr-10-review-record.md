# PR review record — patrickboxfordpartners/bone-fides#10

**PR:** https://github.com/patrickboxfordpartners/bone-fides/pull/10
**Title:** Trust tier 2: a methodology page that states what the data actually is
**Branch:** `feat/trust-tier2` (merged 2026-11-12T20:57:07Z, merge commit `bbfdae87`, branch deleted)
**Final state:** MERGED

## Commits

| SHA | What |
|---|---|
| `f3b8a40` | Tier 2: methodology page, lineage rename, training-claim fix, `published_at` |
| `0bb0ece` | Method page: measure the score distribution instead of leaving placeholders |
| `1488b9e` | Score distribution: measure once offline, not per cold start |
| `d56dca1` | Fix six review findings: broken refresh, outlet mismatch, mapping gap, page copy |
| `1e8feca` | Score sample: score through the dossier path, refuse partial samples |

## Findings

Thirteen inline findings across two bots. **Thirteen real, zero rejected.**

### Round 1 — 11 findings (answered by `d56dca1`)

| # | Bot | Finding | Verdict | Resolution |
|---|---|---|---|---|
| 1 | Greptile P1 | `stamp_score_sample.py` passed an ES client to `_score_sample()`, which treats its arg as a file path → `TypeError` | **Real** (confirmed by running it) | Restored `measure_score_sample(es)` as the computing half; `_score_sample()` stays the reader |
| 2 | Greptile P1 | `method()` counted outlets by `source` only; score used `outlet_tier()` with source_url fallback | **Real** (23 edges differ) | Same rule both places. Eater 4,848→4,849, other 23→22, tiers now sum to 9,312 exactly |
| 3 | Greptile P1 | `ensure_index()` only applied the mapping at creation, so existing indexes could have `published_at` auto-detected as `date` and then reject other formats | **Real** | `ensure_index()` now `put_mapping`s on existing indexes; additive, idempotent, never blocks |
| 4 | Greptile P2 | `score-note` said "Measuring…" forever | **Real** | Reads `measured_at`; reports "Measured 2026-11-12 over a fixed sample of 18 kitchens" |
| 5 | Greptile P2 | Date caveat said the corpus does not record publication dates — contradicted by this very PR | **Real** | Now states forward-only capture, older records lack it, explorer doesn't surface it |
| 6 | Greptile P2 | Formula table gave caps without the normalizations; readers could not reproduce a score | **Real** | Both written out, including why corroboration subtracts one |
| 7 | testdriver | Same as #1 | **Real** | Same fix |
| 8 | testdriver | Same as #4 | **Real** | Same fix |
| 9 | testdriver | `method.html` fetched `/api/stats` a second time for counts `/api/method` already returns; race | **Real** | Duplicate fetch removed |
| 10 | testdriver | Same as #5 | **Real** | Same fix |
| 11 | testdriver | `itemprop="datePublished"` only matched when `itemprop` preceded `content` | **Real** | Both attribute orders added; verified |

### Round 2 — 2 findings (answered by `1e8feca`)

| # | Bot | Finding | Verdict | Resolution |
|---|---|---|---|---|
| 12 | Greptile P1 | `measure_score_sample()` scored raw search hits, skipping `scope_edges()` — sample disagreed with the dossiers it summarizes | **Real.** Measured: 6 of 18 divergent; Tartine 74 vs 64, Atelier Crenn 58 vs 37 | Scores through `assemble_dossier()`. Re-stamped: median **70 → 68** |
| 13 | Greptile P2 | `continue` on a failed search silently shrank the "fixed" sample and still wrote a new stamp | **Real** | Any failure returns `None`; the script leaves the saved file untouched |

Items 2-6 in the second review request were already fixed by `d56dca1` and verified against current code rather than re-fixed.

## Patterns worth carrying

1. **A performance fix relocated a correctness bug.** Moving score computation offline split one function into two, and the split reintroduced the classic mistake: the caller kept passing the old argument to the new half. The refresh command is *documented in the file itself* and still shipped broken, because nothing executed it. A documented command needs a test that runs it.

2. **Two code paths computing "the same" statistic will drift.** The outlet table and the score both answer "how many Eater moves"; one used a `term` aggregation, the other a host-fallback function. They disagreed on 23 edges. Same story at larger scale for the score sample: naive scoring vs `assemble_dossier()` disagreed on 6 of 18 kitchens, by as much as 21 points. **When a page publishes a derived number, it must call the same function the product calls** — not a reimplementation that looks equivalent.

3. **A "fixed" sample that silently shrinks is not fixed.** `continue` on error is the natural shape and it is wrong here: it converts a transient failure into a permanently different published statistic, and still reports success. Fixed inputs require refusing a partial result.

4. **Placeholders are promises.** `score-note` shipped reading "Measuring…" on the page whose entire purpose is measuring. It was rendered, styled, positioned correctly, and never written by any code path. A placeholder with no writer is indistinguishable from working code in a diff.

5. **Copy can contradict a PR one file away.** The methodology page asserted "the corpus does not record article publication dates" in the same branch that added `published_at`. Two bots flagged it independently. Any PR that adds a capability must grep the docs for the claim that it is absent.

## Verification at merge

- 216 tests pass, 3 skipped
- Twin parity: structurally identical across shared functions, 3 documented allowlist entries (`venues_geo`, `_facet_probe`, `_score_sample` — root path or import order only)
- Live `https://bone-fides.vercel.app/api/method` → `scores: {n:18, min:37, max:79, median:68}`, tiers sum 9,312 of 9,312 edges
- `/`, `/explorer`, `/method` all 200; no console errors
