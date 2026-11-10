# Bone Fides — Roadmap (specced 2026-11-10)

Five proposals reviewed against the corpus and the codebase. Each spec lists
what exists today, what gets built, the honest costs, and the non-goals.
Order at the bottom. Nothing here is committed to a date.

Measured corpus facts these specs rest on (probed 2026-11-10):

- 9,312 edges / 3,113 people / 8,155 city venues; 2,219 cited sources
- role filled on 9,311/9,312 edges, but raw values are messy
  (3,034 "chef", 349 "Chef", 635 "executive chef", 310 "chef-owner"...)
- date filled on only 1,454/9,312 edges (15.6%); formats are loose
  ("2015", "January", ...)
- neighborhood filled on 8,141/8,155 city venues (99%), 100+ distinct labels
- non-SF venues (Gramercy Tavern, French Laundry, Meadowood) are already
  normal graph nodes: 540 edges touch them

---

## 1. Corrections layer ("Suggest a correction / submit a tip")

**Problem.** The footer invites corrections and source tips, but there is no
in. The citation gate keeps the corpus credible; a tip inbox keeps it growing
without waiting for the next manual scrape run.

**Build.**

- Affordance: a quiet "Flag or add" link on every kitchen dossier, every chef
  dossier, and per cited edge (each move row). Opens a native `<dialog>`
  (no framework, matches the vanilla-JS codebase).
- Form fields, all prefilled where possible:
  - type: wrong person / wrong venue / wrong detail / add a move / add a source
  - source URL (required for "add a move" and "add a source", optional
    otherwise) — the corpus is built on citations, tips should arrive with one
  - note (optional, ≤500 chars)
  - honeypot field (invisible; filled = silently accepted and dropped)
- Endpoint: `POST /api/tip`. Both twins: a branch in `server.py`'s router, a
  `do_POST` on the Vercel handler delegating to a new `_dispatch_tips`.
- Storage: new ES index `bone-fides-tips` (credentials already reach both
  runtimes; Vercel's filesystem is read-only so a flat file is not an option).
  Doc shape: `{query, context_edge_id?, venue?, chef?, type, url?, note, ip,
  created_at, status: "open"}`. Tips are NEVER auto-ingested — the citation
  gate (`citation_supported` + `evidence_in_article`) is the product, and the
  inbox exists to protect it, not bypass it.
- Rate limit: reuse `allow_request`, bucket `"tips"`, 5/hour/IP. Size caps on
  every field.
- Triage: `src/review_tips.py` CLI (list open tips, mark
  resolved/rejected/ingested). Tips get reviewed during corpus-growth
  sessions, same discipline as the manual scrape runs today.

**Costs.** ~1.5-2 build sessions. The real cost is operational: a triage
habit. An inbox nobody reads is worse than a footer that promises nothing.

**Non-goals.** No user accounts, no public voting on corrections, no auto-
publish, no captcha (rate limit + honeypot is proportionate).

---

## 2. Watchlists / bookmarks (reduced scope: local only)

**Problem as proposed.** Accounts, saved kitchens, followed chefs, move
alerts. Declined in full — three compounding costs:

- auth + per-user storage: infrastructure this stateless serverless+ES stack
  doesn't have;
- move alerts presume continuous ingestion; the corpus grows in periodic
  scrape runs, so alerts would arrive weeks late unless we also build a cron
  crawler + email delivery;
- a watchlist's event rate is a handful of moves per year — poor cost/value.

**Build (the honest slice).** "My kitchens": a bookmark affordance on
dossiers and roster rows, persisted in `localStorage`, rendered as a tray on
the explorer ("Your kitchens" chips above the seed list). No server state, no
accounts, no sync, no promises.

**Costs.** ~0.5 session.

**Non-goals.** No accounts, no cross-device sync, no notifications. If usage
data shows people returning and wanting sync, revisit with accounts then.

---

## 3. Hub network graph (scoped: one kitchen at a time)

**Problem as proposed.** Whole-city node-link graph of 3,113 chefs. Declined
as stated — an unreadable hairball, mobile-hostile, and the explorer's
per-chef chains already cover person-scale stories. The on-brand slice is
the hub view: "where did this kitchen's people go, and who came up through
here?"

**Build.**

- Entry: "View as tree" affordance on kitchen dossiers (visible when the
  query resolved to a venue).
- Layout: hand-rolled SVG (no d3 — no build step in this repo, our shape is
  simple, and a CDN dep is only justified if hand-rolling fights back).
  Radial two-sided tree: hub center, inbound cited moves (people who came to
  the hub) branching left, outbound (where they went next) branching right.
- Node = venue chip (existing `.vchip` styling); click = `pick()` into the
  dossier, consistent with chain interaction. Edge = cited move, confidence
  color from the existing legend, year label when dated.
- Data: everything `/api/search?q=<venue>` already returns; no new endpoint.
- Mobile (≤640px): the two-sided tree becomes a vertical branch list
  (inbound above, outbound below) — same DOM, CSS layout switch, honest at
  375px where a zoomable force graph is unusable.
- Person queries: hide the toggle (the chain view already IS the person
  graph).

**Costs.** ~2-3 sessions — the largest build here. SVG layout + touch
behavior is where the time goes.

**Non-goals.** No whole-city graph, no pan/zoom canvas, no physics
simulation, no new data.

---

## 4. Faceted filtering (incremental, in data-order)

**Problem as proposed.** Era, role, and neighborhood facets corpus-wide.
Measured reality: role is rich but messy; dates exist on only 15.6% of edges
(era facets would silently blank 84% of the corpus); neighborhoods live on
city venues, not edges, so edge-level joins are approximate until index-time
enrichment.

**Build, in data-order:**

1. Role normalizer (`src` shared helper + both twins): raw role text →
   bucket {chef, executive chef, pastry, sous, owner, bartender, other}.
   Same discipline as `norm_venue` — case fold, synonym fold, no substring
   guessing. Add tests alongside the existing `_fuzzy_sibling` ones.
2. Dossier-level role chips: filter a dossier's rows by role bucket,
   client-side, with counts. Honest and cheap — the rows are already there.
3. Server facet params: `/api/search` gains `&role=<bucket>` and
   `&era=<from>-<to>` filtering the ES query (era applied only to dated
   edges, with a visible "dates on 15% of cited moves" note when active so
   the filter never lies by omission). **Shipped 2026-11-09, role only:**
   role_bucket stamped at index time (one-off backfill run, 9,312 docs)
   and `&role=` applies as a post_filter — it gates the final RRF hit list
   without touching ranking, and this ES version rejects sparse_vector
   nested in bool, so the planned retriever-level filter was impossible.
   The explorer honors `?role=` permalinks and discloses the filter; chip
   clicks under an active server filter refetch server-side. Era facet
   NOT built: dates are loose strings ("2015", "January") on 15.6% of
   edges — a query param can't filter them honestly. Era needs index-time
   date normalization, which is a data run (4.4 territory).
4. Neighborhood pipeline facet: deferred. Requires venue→neighborhood
   enrichment at index time (join via the `tag_city` normalization
   discipline) — a data task, not a UI task, and needs its own run.
   **Shipped 2026-11-09 (as 4.4, with era):** `src/eras.py` normalizes
   loose dates to era buckets {pre-1990, 1990s, 2000s, 2010s, 2020s} —
   word-boundary year extraction only, ranges anchor on the FIRST year
   (arrival era), relative dates ("recently") never yield a bucket; 1,166
   of 1,454 dated edges carry a citable year. `src/hoods.py` joins
   venues→neighborhoods: flagship-row rule (shortest name per lineage
   key, the same row the map pins), majority-vote permit rows, unambiguous
   token-prefix fallback, plus a curated CLOSED_SF map for 46 venues the
   current-permit snapshot cannot see — every curated hood verified
   against the city file's own block-level labels; non-SF venues stay
   unstamped (nothing invents an SF hood for Chez Panisse). Both stamped
   at index time (`era_bucket`, `venue_hoods`) and backfilled (9,312
   docs): 12% of edges carry an era, 43% carry a hood. `&era=` / `&hood=`
   post_filter over the RRF window, composed with role gates; the
   explorer renders chips with click-to-clear, honors permalinks, and the
   facet-empty state is honest — "is in the record, but none of its
   cited moves carry era X" with the coverage disclosure (dates on 15%,
   neighborhoods on 43%) and a clear-the-filter affordance. Two probe
   lessons: a size=0 window collects NOTHING for post_filter to gate (the
   RRF window is the only pool it sees — probes need a real, deep
   window), and when the gates empty the retrieval window itself,
   resolution fails before the facet-aware branch, so the unresolved
   path probes the UNGATED record to distinguish "facet emptied a real
   dossier" from "not in the record."
   **Review pass (2026-11-10):** a second-pair-of-eyes review of the
   shipped 4.4 work found five verified defects, all fixed and locked by
   tests (tests/test_review_3330654.py): the local twin dropped
   plus-encoded facet params (spaces in hood/role values silently
   unmatched); CLOSED_SF lookups were raw-string (curly apostrophes,
   case, articles fell through); the token-prefix fallback stamped SF
   hoods on out-of-city parentheticals and single-token permit keys
   prefix-claimed multi-token venues; the role facet-clear chip was dead;
   and the completion merge pulled ungated homonym edges past the facet
   gates. Honesty follow-ups: the facet-empty branch now also gates on
   the role filter (a role-only empty said "not in the record" while the
   ungated record HAS the name) and names the filter from the
   server-validated echo; the coverage note names only the facets in the
   message; the facet-empty probe forwards role and honors the citation
   gate; the era regex stamps decade-suffixed dates ("1970s") without
   lying about relative dates. Corpus re-stamped after the normalizer
   fixes (9,312 docs).

**Costs.** Steps 1+2 ~1 session; step 3 ~0.5; step 4 is a separate data
project.

**Non-goals.** No faceted homepage, no saved filter sets, no neighborhood
claims before the enrichment exists.

---

## 5. Professional surface (declined as proposed; free slice only)

**Problem as proposed.** Recruiter view, verified lineage credentials,
claim-your-dossier. Declined: "verified credentials" puts the site's
authority behind identity claims, and identity is exactly what the corpus is
careful about (homonyms are flagged "possibly two people," never merged).
Claim flows invite gaming; a B2B tier changes the product's relationship
with its sources.

**Build (the free slice).** Every dossier is already a permalinked, sourced
credential (`/explorer?q=...`). Add: a "copy link" affordance on dossiers and
a print stylesheet so a dossier prints as a clean one-pager (citation list
intact). Zero server work.

**Costs.** ~0.5 session.

**Non-goals.** No auth, no claims, no badges, no recruiter tier. Revisit only
on real inbound demand from operators.

---

## Build order and rationale

1 → 4.1+4.2 → 3 → 2 → 5.1 → (4.4 as a standalone data run)

- 1 first: it compounds everything after it (better tips → better corpus)
  and it is the product-integrity win.
- 4.1+4.2 before 3: the role normalizer makes the graph's edge labels honest,
  which the tree renders directly.
- 3 third: biggest UX build, done after the cheap compounding wins.
- 2 and 5 are fillers between bigger pieces, not roadmap anchors.

**Status 2026-11-09: the build order above is complete** — 1 (corrections
layer), 4.1+4.2 (role normalizer + dossier role chips), 3 (hub tree), 2
(My kitchens watchlist), 5.1 (copy link + print stylesheet), 4.3's
role facet, and 4.4 (era buckets + venue→neighborhood enrichment for the
era and neighborhood facets) all shipped with tests, twin sync, and
browser verification. Nothing remains from this roadmap.

Each step ships straight to main with tests, twin sync (`build.sh`), and a
prod verification pass, same as every change in this repo.
