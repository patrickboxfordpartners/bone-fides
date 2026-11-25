# Flagship release: plan and mockups

Status: **planned, not built** (2026-11-25). Nothing in this folder is served by the site.

The goal is to make the cited graph visible, for diners and for investors: a family tree per kitchen, the shortest chain of cited moves between any two kitchens, a rankings page, a rebuilt landing page and a live "By the numbers" page.

## What is here

| File | What it is |
|---|---|
| `plan.md` | The full plan: the citation-gate fix with its proof, the graph file and API, each view, tests, the 10/10 scorecard and the five-step release sequence. Start here. |
| `brief.md` | The owner's decisions and the constraints the plan and mockups were made to. |
| `data-brief.json` | Prototype figures and real sample trees and chains, from displayed (gated) moves only. |
| `mockups/` | 21 HTML mockups (open in a browser) and their two design-plan files. `views-*` are the Tree, Connect, Ledger and header; `front-*` are the landing page and By the numbers. |

## Owner decisions already made

1. Pitch: a consumer front, with a data business behind it.
2. Scope: flagship features on the current look; no new visual identity.
3. A public, live "By the numbers" page for investors.
4. Fix the citation gate first, with proof: at least 95% of a hand-labelled sample of newly displayed moves must be true.
5. Draft merges for kitchen names split by a bracketed note, for the owner to review.
6. Investor page contact: `patrick@boxfordpartners.com`. Next market named: the wider Bay Area.

Still open: the Tree layout (rings is recommended over descent) and the landing hero (tree is recommended over line). The plan supports both.

## To resume

Build in the order of `plan.md` section 18. Step 1 (the gate fix) comes first, because every figure in the later views depends on it. A lean first slice is step 1 plus the Tree view.

## Known loose ends in the mockups

- Figures are prototypes on today's gate. Built views take every figure from the API.
- The French Laundry tree in `data-brief.json` states 61 kitchens (rings of 15, 22, 24) but lists 60 (15, 21, 24). The graph builder in the plan is the one definition; use its count.
- Header labels: the mockups say "Explore" and "Trees"; the plan text says "Explorer" and "Tree". Pick one.
- The numbers mockup offers "a sample export" in its contact section. No export exists; remove the offer or build it.
- The green "corroborated" dot on one move rests on two articles from the same outlet. Decide whether corroboration needs two different outlets.
- `data-brief.json` had one false chain, Manresa to Californios: the quote is a guest takeout series, which today's gate accepts. It is removed and noted in the file. Californios still appears as a starred kitchen within three moves of Manresa and Gary Danko in the ledger rows and mockups; treat that as overstated until the gate work measures it.
- A per-tree share image is designed (`views-tree-share-card.html`) but deferred in the plan.
