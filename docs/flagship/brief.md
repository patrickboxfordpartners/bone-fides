# Bone Fides flagship brief

State when written: branch `main`, commit 941adee (2026-11-25). Live site: https://bone-fides-pat-mitchells-projects.vercel.app

## What Bone Fides is

A cited kitchen-lineage graph of San Francisco. 9,312 chef moves, 3,119 chefs, 4,412 kitchens, 2,221 source articles. Every move links to the article that reported it and carries the quoted evidence. A citation gate keeps only moves the quoted text states.

Today the site has three pages, each a single vanilla HTML file with inline CSS and JS, no build step:
- `ui/landing.html` — marketing page
- `ui/explorer.html` — search rail (dossier of one kitchen or chef) beside a Mapbox map
- `ui/method.html` — how the score works

API: one Python function, `src/dossier.py` `dispatch()`, backed by Elasticsearch (`src/es_query.py`). Endpoints today: `/api/search`, `/api/suggest`, `/api/stats`, `/api/method`, `/api/venues`, `/api/tip`, `/api/map.js`. `vercel-app/build.sh` copies pages to `public/` and modules plus data files to `api/_lib/`; page routes are rewrites in `vercel-app/vercel.json` and `PAGES` in `ui/server.py`.

Design system: `docs/DESIGN.md`. One warm-dark theme, Fraunces serif, tokens in `:root`. Voice: editorial, evidentiary, restrained. "Numbers are claims — always tabular, always traceable to a source link."

## The owner's decisions (binding)

1. **Pitch:** consumer front, data business behind. The site is public proof that diners explore and book by pedigree. The investor story is that the cited graph is a data asset (talent intelligence for restaurant groups, landlords, media) that expands city by city.
2. **Scope:** flagship features on the current look. Keep the warm editorial identity. Add 3 to 4 showpiece features that make the graph visible, and rebuild the landing page around them. No new visual identity.
3. **Investor page:** yes, a public, live "by the numbers" page. Every figure is real and comes from the graph.
4. **Bar:** the owner wants a 10/10. Flair and function must both make sense. Nothing decorative that the data cannot back.

## The problem to solve

The site shows one kitchen at a time. The graph's most impressive facts are invisible. Figures below count only moves the site displays (those that pass the citation gate); see `plan.md` for how they were measured and how they are expected to rise after the gate fix.

- The French Laundry: 15 alumni, about 60 kitchens within three moves, 6 of them Michelin-starred (Angler, Benu, Mister Jiu's, Quince, San Ho Won, Ssal).
- Chez Panisse has 21 documented alumni.
- Five chefs name Thomas Keller as their mentor in a displayed quote.
- 19 to 20 of the city's 26 Michelin-starred kitchens are linked in the graph.
- Kitchens in the main connected set can be joined by a short chain of cited moves.

An earlier draft of this brief gave larger figures (262 kitchens, 12 starred, 37 alumni). Those counted all 9,312 extracted moves, including the ones the site does not display. Do not use them.

## Flagship concepts (starting point; improve on them)

1. **The Tree** — a kitchen's family tree. Generations of alumni and the kitchens they went on to run, starred kitchens marked, every branch a cited move. Shareable by link. The single most demo-able view.
2. **Connect / "Trace a line"** — pick any two kitchens or chefs; show the shortest chain of cited moves between them, each hop with its person, quote and source. Playful, and it proves the graph is real.
3. **The Ledger** — rankings: kitchens that produced the most chefs, widest reach, most starred descendants; top mentors; the starred kitchens and where their chefs came from. Each row opens the tree or dossier.
4. **Landing rebuilt** — hero that shows the graph doing something (a live tree or a connection), then the three features, then proof.
5. **By the numbers** (investor page) — live corpus numbers, how the citation gate works and why it is a moat, source mix, coverage and what is honestly missing (only 1,454 of 9,312 moves on record carry a year), booking coverage (222 verified venues), the path to the next city, contact.

Also in scope if they earn their place: a share image per tree or dossier, a consistent header/navigation across pages (there is none today), and anything that makes the consumer loop tighter (explore → trust → book).

## Real data

`docs/flagship/data-brief.json` holds real figures pulled from the live index: corpus stats, the top alumni kitchens with reach and starred descendants, top mentors, source mix, two real trees (French Laundry, Chez Panisse) and four real shortest paths with people, quotes and sources. Use these, not invented names or numbers.

## Hard constraints

- Honesty is the brand. No fabricated numbers, no claim the citations do not support. A tree edge or a path hop is a cited move by a named person, not "influence".
- Vanilla HTML/CSS/JS per page, no framework and no build step. Python stdlib plus `elasticsearch` on the server.
- The graph is small (9,312 edges). Server work must stay fast on a cold Vercel function.
- Must work without WebGL and at 390px and 1440px.
- Accessibility: keyboard reachable, focus visible, AA contrast, reduced motion respected. A graph view needs a readable non-visual equivalent (the explorer's tree already has a list form).
- Booking links appear only where verified for that exact name (`ui/dossier_booking.json`).
