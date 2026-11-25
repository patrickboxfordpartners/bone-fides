# Bone Fides

A kitchen-lineage explorer for San Francisco. Type a restaurant or a chef and
get its bone fides: where the kitchen's people came from and where its alumni
went, with a cited article on every edge.

The corpus is built from public food journalism (Eater SF, the Chronicle,
SFGate). Mistral extracts person/venue moves from each article, a citation gate
keeps only moves the quoted text actually states, and Elasticsearch serves
hybrid (fuzzy keyword + semantic) search over the result.

## Layout

| Path | What it is |
|---|---|
| `src/` | The library. `dossier.py` is all query/dossier logic for the web API; `es_query.py` the ES client and search; `es.py` index mapping and doc building; `extract.py`, `fetch.py`, `pipeline.py` the extraction pipeline; `venue_images.py`, `hoods.py`, `eras.py`, `roles.py`, `venue_aliases.py` corpus enrichment. |
| `scripts/` | Command-line entry points: corpus planning and growth, backfills, tip triage, image publishing, `build_graph.py` (the committed graph), `measure_gate.py` (the citation-gate measurement), `sync_chrome.py` (the shared header and footer). Run from the repo root. |
| `ui/` | The front end (`landing.html`, `explorer.html`, `method.html`, `tree.html`, `connect.html`, `ledger.html`, `numbers.html`, `lineage.js`, `map.js`), its data files (`graph.json`, `venue_aliases.json`, `gate_stamp.json`, `og.png`), and `server.py`, the local demo server. |
| `vercel-app/` | The Vercel deployment. `api/search.py` is the one Python function; `build.sh` assembles everything else from `ui/` and `src/` at deploy time. |
| `crawl/` | Crawl plans and caches the scripts read and write (URL lists, seen URLs, image records). |
| `tests/` | pytest suite. |
| `docs/` | `DESIGN.md` (visual design), `ROADMAP.md` (specced next steps). |
| `READING-LIST.md` | The seed source list `src/sources.py` parses. |

`ui/server.py` and `vercel-app/api/search.py` are thin HTTP adapters around
`src.dossier.dispatch()`, so the local demo and the deployed site run the same
code. `tests/test_shared_core.py` keeps it that way.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # ELASTIC_ENDPOINT, ELASTIC_API_KEY, MISTRAL_API_KEY; MAPBOX_TOKEN for the map
.venv/bin/python ui/server.py # http://127.0.0.1:8017
.venv/bin/python -m pytest -q
```

## Build the corpus

```bash
.venv/bin/python -m src.cli ingest                 # READING-LIST.md -> Mistral -> ES
.venv/bin/python scripts/plan_corpus.py            # Eater SF URL plan -> crawl/eater_urls.json
.venv/bin/python scripts/grow_corpus.py            # discover, extract and index more articles
.venv/bin/python scripts/plan_chron.py && .venv/bin/python scripts/grow_chron.py   # same for the Chronicle
.venv/bin/python -m src.cli ask "Betelnut"         # query from the shell
```

Backfills that stamp derived fields onto existing docs live in
`scripts/stamp_*.py`. Reader tips (`POST /api/tip`) go to a separate
`bone-fides-tips` index and are triaged with `scripts/review_tips.py`; nothing
enters the corpus without the citation gate.

## Venue photos

`src/venue_images.py` resolves a photo per venue (the venue's own site first)
and downloads it into `ui/venue-images/` (gitignored).
`scripts/publish_venue_images.py` uploads those files to the
`bone-fides-venue-images` Vercel Blob store and rewrites
`crawl/venue_images.json` to the public URLs. It needs
`VENUE_IMAGES_READ_WRITE_TOKEN`, which the Vercel project already has.

## Deploy

The Vercel project `bone-fides` (team pat-mitchells-projects) deploys from
`main` with root directory `vercel-app/` and "Include source files outside of
the Root Directory" on. `build.sh` copies the pages into `public/` (the only
static output) and the dossier modules and data files into `api/_lib/`. Every
branch push gets a preview deployment.

Environment variables on the project: `ELASTIC_ENDPOINT`, `ELASTIC_API_KEY`,
`MAPBOX_TOKEN`, `VENUE_IMAGES_READ_WRITE_TOKEN`.
