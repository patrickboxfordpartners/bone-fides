# Bone Fides flagship release

Repository: `the repository root`, branch `main`, commit 941adee.
Brief: `docs/flagship/brief.md`. Gated sample data: `docs/flagship/data-brief.json`. Mockups: `docs/flagship/mockups/`.

## Approach

The release makes the cited graph visible. It first repairs the check that decides which moves the site shows. It then adds four views and one investor page on the current visual identity. It adds no visual token.

- First, the display gate (`citation_supported`) is widened to accept true career statements that it rejects today. The change ships only with proof: a hand-labelled random sample of the newly accepted moves must be at least 95% true. The method page states the measured precision.
- One graph file holds every displayed move. A script builds the file from Elasticsearch after each corpus update. The file is committed and ships in the function bundle.
- One new module, `src/graph.py`, reads the file. It computes trees, shortest chains and rankings in memory.
- `dossier.dispatch()` serves the module through five new endpoints. Four of them do not call Elasticsearch.
- Four new single-file pages: `/tree`, `/connect`, `/ledger`, `/numbers`. The landing page is rebuilt. All seven pages get one shared header.
- One shared script, `ui/lineage.js`, draws the tree and the chain. It uses SVG and HTML only. No framework, no WebGL, no build step.
- Every figure on every page comes from an API payload. No page holds a typed figure.

### The gate decides the figures

The record has two filters.

1. Extraction check (`src/extract.py` `evidence_in_article`): the quote is verbatim in the article. All 9,312 moves pass.
2. Display gate (`src/dossier.py` `citation_supported`): the quote itself states a career move. 3,388 of 9,312 pass today (36%). A dossier shows only these moves.

The first brief counted all 9,312 moves. The data brief now holds gated figures. The owner's decision is to fix the gate first, with proof. The table gives measured figures for the first two columns and an estimate for the third. I measured the estimate with three prototype cue sets on the cached moves.

| Figure | All 9,312 moves | Current gate (measured) | After the gate fix (estimate) |
|---|---|---|---|
| Moves displayed | 9,312 | 3,388 | 4,700 to 5,900 |
| Hops between two named kitchens | 4,058 | 1,625 | 2,500 to 3,000 |
| Linked kitchens; largest connected set | 3,293; 1,617 | 1,587; 631 (40%) | 2,100 to 2,400; 1,050 to 1,200 (about 50%) |
| French Laundry alumni | 25 | 16 | 19 to 20 |
| French Laundry: kitchens within three moves | 262 | 60 | 145 to 165 |
| French Laundry: starred kitchens within three moves | 12 | 6 | 8 |
| Chez Panisse: alumni and kitchens | 37 and 31 | 21 and 19 | 32 to 33, and 27 |
| Thomas Keller: chefs who name him as mentor | 9 | 5 | 6 to 7 |
| Starred kitchens linked in the graph | 24 of 26 | 20 of 26 | 23 to 24 of 26 |

- The estimate holds only if each cue family passes the precision test. A family that fails is removed. The figures then fall toward the middle column.
- The data brief and this plan used prototype rules that differ in small details. Their figures differ by 1 or 2. The builder in section 4 is the one definition.
- "Thomas Keller is the named mentor of 21 chefs" was never correct. 21 is a count of moves.
- No figure in this table is typed into a page. The pages read the graph file and the API.

## Design and important details

### 1. The gate fix (first pull request)

#### 1.1 What is wrong today

5,924 moves fail the gate. The reasons, measured on the cached moves:

| Reason | Moves |
|---|---|
| The quote has no word from `_MOVE_CUE` | 5,479 |
| The role or quote has a `_NONCAREER` word (guest chef, pop-up, supplier, purveyor, vendor) | 323 |
| The action is `PROMOTED` and the quote has no promotion word | 122 |

Many of the 5,479 are true career statements. `_MOVE_CUE` knows "formerly" but not "former". It does not know "veteran", "vet", "alum", "stints at", "most recently", "was last at", or a credential list in parentheses. The owner's five examples are all in this group.

#### 1.2 The code change

All changes are in `src/dossier.py`. `_MOVE_CUE`, `_PROMO_CUE` and `_NONCAREER` do not change.

- New `citation_reason(edge)`. It returns `"move"` or `"promotion"` when today's logic accepts the move. If not, it returns the name of the new cue family that accepts the move, or `None`.
- `citation_supported(edge)` becomes `citation_reason(edge) is not None`. Its three call sites do not change: `assemble_dossier`, `_cited_moves_exist`, and `parse_extraction` in `src/extract.py`.
- Today's logic runs first and is not edited. So every move that is displayed today stays displayed.
- A new cue applies only when all these conditions are true:
  1. The quote is not empty and has no `_NONCAREER` word. The role has none.
  2. The action is not `PROMOTED`. Promotions keep their own rule.
  3. The quote names a venue of the row (the anchor rule). The match uses whole tokens from `venue_key_words()`, the same discipline as `_venue_touch`. "El Faro" does not match "El Farolito". 4,230 of the 5,479 quotes pass this rule.
  4. The quote has no guard phrase from the new `_NOT_A_STINT` pattern (section 1.4).
  5. A pattern of a cue family in the new `_CAREER_CUES` table matches.

`_CAREER_CUES` is a table of family name to pattern. A family is in the table only if it passed the test in section 1.6.

#### 1.3 How candidate cues are derived from the rejected set

New script `scripts/measure_gate.py`. It reads all moves from Elasticsearch, or from a cached file with `--edges <path>`.

1. `--mine` takes the moves with no cue and counts phrases of one to three words by the number of quotes that hold them. It writes the top 300 to `crawl/gate_review/phrases.json`. The frequent career phrases today: "former" (362 quotes), "most recently" (73), "executive chef at" (72), "comes from" (52), "chef de cuisine at" (51), "stints at" (49), "chef-owner of" (39), "the kitchens of" (30), "at the helm" (26), "a veteran of", "an alum of", "includes time at", "brings experience from".
2. The build agent groups the phrases into candidate families. Each family is one pattern with word-order limits, not a list of loose words.
3. `--report` gives, for each family, the number of newly accepted moves with and without the anchor rule.

Candidate families and their size today (no-cue moves that match; with the anchor rule):

| Family | Examples | Matches | With anchor |
|---|---|---|---|
| `tenure` | "former Quince sous Jared Sippel", "eight year veteran of the French Laundry", "the French Laundry vet", "who was last at", "most recently at", "stints at", "Tartine alums" | 1,094 | 998 |
| `credential` | a parenthesis after a name or role that holds a venue of the row: "Dustin Falcon (Morimoto, Ad Hoc, The French Laundry)", "(Cyrus, The French Laundry)" | 355 | 352 |
| `title` | a job title joined to a venue: "chef-owner of Relæ", "executive chef at Frascati", "was the sous chef at" | 667 | 622 |
| `lead` | "at the helm", "has taken over", "will run the kitchen", "brought on as" | 732 | 553 |
| `opening` | "is opening", "debuted", "first restaurant", "from the team behind" | 907 | 769 |

2,593 no-cue moves match no candidate family. They stay rejected.

A first reading of 40 `tenure` rows found 3 or 4 false ones. The causes: "former" that describes a space ("the former Coco500 space"), "former" that describes other people ("sold to former employees"), and "comes from" that describes income. So the `tenure` pattern must tie "former" to a role word or a venue name, and must not accept "former ... space, location, home or site". `credential` and `title` read cleaner. `lead` and `opening` are the weakest candidates and are the first to go if they fail.

#### 1.4 What the widened gate must still reject

- `_NONCAREER` stays first and stays a hard veto: guest chefs, pop-ups, suppliers, purveyors, vendors. 153 moves carry a new cue and stay rejected by this veto.
- `_NOT_A_STINT` is a new guard for the new cues only. It covers what `_NONCAREER` does not: a guest dinner or guest appearance, a collaboration dinner or menu, a one-night event, a dinner series, a takeover, "inspired by", "sources from" and "supplied by".
- A row whose venue is a television show, an award, an event or a festival ("Top Chef", "Farmstock 2K12 (event)") is not a stint. The guard rejects it.
- A guard phrase enters `_NOT_A_STINT` only when the development sample shows that it marks false rows. A blunt word list would reject true rows. "Collaboration" alone is not a guard: "chef John Paul Carmona (Manresa)" in a sentence about a collaboration is a true credential.
- Each rejected kind has real rows in the must-reject fixtures (section 1.7). The test fails if one of them passes.

#### 1.5 The labelling protocol

What counts as true. A row is true when a reader can see the career fact in the quotation:

1. The quote is about the person in the row.
2. The quote states that the person holds or held a job, an ownership, a founding role, a training stint or an apprenticeship at a venue named in the row.
3. For a row with two venues, the quote supports at least one venue and does not contradict the other venue or the direction. The labeller also records `both` (true or false): the quote supports both venues.
4. The venue is a food or drink business or a cooking school. It is not a show, an award, an event or a festival.

A row is false when the quote describes a guest dinner, a one-night collaboration, a pop-up at the venue, a supplier relation, an inspiration, a meal eaten, a review, an award, a move of the restaurant itself with no statement about the person, a different person, or the opposite direction. A row with an unnamed person is false.

A quote that refers to the person only by a pronoun needs the article. The labeller opens the source URL to confirm who the pronoun is. If the page does not load, the label is `unsure`. `unsure` counts as false.

Samples. `scripts/measure_gate.py --sample` draws them. A row id is the SHA-256 of source URL, person, venues and quote. A sample is the n rows with the smallest hash of seed plus id. So the script draws the same sample again from the same corpus.

| Sample | Drawn from | Size | Use |
|---|---|---|---|
| Development | newly accepted moves, 40 for each candidate family | 200 | tune patterns and guards; may be read freely |
| Acceptance | all newly accepted moves, after the patterns are frozen | 400 | the owner's 95% rule |
| Baseline | the 3,388 moves displayed today | 200 | precision before the change, for the method page |

Who labels:

- The build agent labels each row with a label and a one-line reason.
- A second agent labels the acceptance and baseline samples without the first labels.
- A row counts as true only when both labels are true.
- The owner reviews the labelled file in the pull request. The file lists false and disputed rows first.

#### 1.6 The acceptance rule

- Overall: at least 95% of the 400 acceptance rows are true (380 or more).
- Each family with 30 or more rows in the sample: at least 90% true.
- If a rule fails, the build agent changes or removes the pattern. It then draws a new acceptance sample with a new seed and labels it again. A sample that was used to change a pattern cannot prove that pattern.
- The file records each round: seed, pattern hash, counts.
- If no cue set reaches 95%, the pull request ships no new cue and reports the measured figures.

The method page states the point figure, the sample size, the date, and the 95% lower bound (Wilson). With 388 true of 400 the figure is 97.0% and the lower bound is 94.8%.

#### 1.7 Where the proof is stored

`tests/fixtures/gate_labels.json` (committed; the test reads it):

```json
{
  "protocol": 1,
  "measured_at": "2026-11-26",
  "cue_hash": "sha256 of the pattern sources of _CAREER_CUES and _NOT_A_STINT",
  "corpus": {"on_record": 9312, "displayed_before": 3388, "displayed": 0, "newly_displayed": 0, "lost": 0},
  "rounds": [{"seed": "a1", "cue_hash": "...", "n": 400, "true": 0, "result": "pass"}],
  "samples": {
    "acceptance": [{"id": "...", "person": "...", "from_venue": "...", "to_venue": "...", "role": "...",
                    "action": "...", "evidence": "full quotation", "source_url": "https://...",
                    "family": "tenure", "label": "true", "both": false, "second_label": "true", "note": "..."}],
    "baseline": [],
    "development": [],
    "must_reject": [{"kind": "guest dinner", "person": "...", "evidence": "...", "note": "..."}]
  }
}
```

The zero values are slots that the script fills. Each row holds its full quotation, so the test needs no index.

`ui/gate_stamp.json` (committed; shipped in the bundle; read by `method()` through `data_path("gate_stamp.json")`):

```json
{"measured_at": "2026-11-26", "on_record": 9312, "displayed_before": 3388, "displayed": 0,
 "newly_displayed": 0, "sample_n": 400, "sample_true": 0, "precision": 0.0, "precision_low": 0.0,
 "both_share": 0.0, "baseline_n": 200, "baseline_true": 0, "by_family": {"tenure": [0, 0]}, "cue_hash": "..."}
```

`scripts/measure_gate.py --stamp` writes both files. `--check` reads the live index and confirms three facts: no move that was displayed before is lost, the samples come again from their seeds, and the counts equal the stamp.

#### 1.8 How the already-displayed moves are protected

- By construction: today's logic runs first and is not edited. The new cues can only add moves.
- By test: the pattern sources of `_MOVE_CUE`, `_PROMO_CUE` and `_NONCAREER` are pinned by hash in the test. A silent edit fails.
- By measurement: `--check` must report `lost: 0` on the full corpus.
- By disclosure: the baseline sample gives the precision of the moves displayed today. The method page states it beside the new figure. The site then never claims that the old set was perfect.
- The guards in `_NOT_A_STINT` do not run on today's path. If the baseline sample finds false rows in today's set, they go into the pull request description. A removal of displayed moves is a separate decision.

#### 1.9 Effects on other parts of the site

- No reindex. The gate runs when a dossier is read, not when a move is indexed.
- Dossiers show more rows. Measured on the live index with a prototype: the 18 kitchens of the score sample go from a mean of 7 displayed moves to about 13.
- Lineage scores rise, because `pedigree()` counts displayed moves and their articles. Measured with the same prototype: the sample goes from minimum 37, median 68, maximum 79 to about minimum 64, median 74, maximum 79. Rich Table goes from 37 to about 66. The formula does not change.
- `ui/score_sample.json` is measured again with `scripts/stamp_score_sample.py` in the same pull request. The pull request description lists the 18 scores before and after.
- `/api/stats` does not change. It counts moves on record, people, kitchen names and articles. None of them use the gate.
- `/api/method`: `coverage` and `tiers` do not change. `scores` changes through the new stamp. The payload gains `gate`, the content of `ui/gate_stamp.json` without `cue_hash`. If the file is missing, `gate` is `null` and the page says that precision is not measured.
- `method.html`: a new block states the displayed share, the measured precision with its sample size, lower bound and date, the baseline figure, and the share of two-venue rows whose quote names both kitchens. The sentence about the citation gate lists the new kinds of statement it accepts. All figures are slots filled from `/api/method`.
- `landing.html` holds a stored Betelnut example with a score. The pull request checks it against the live dossier and corrects the stored copy. The landing rebuild later removes stored figures.
- Ingestion: `parse_extraction` calls the same function. New articles are then admitted with the wider cues. The verbatim check on the quote still applies.
- `build.sh` copies `ui/gate_stamp.json` to `api/_lib/`. The existing test forces this, because `dossier.py` reads it with `data_path()`.

### 2. What a branch or a hop is

Tree, Connect and Ledger use one definition. A hop is one indexed move document that meets all these conditions:

1. `dossier.citation_supported(move)` is true. The check reads the full quotation.
2. The person is named: `dossier._is_collective(person)` is false. This removes "sous chef", "a duo of chefs" and similar strings.
3. The move has a `from_venue` and a `to_venue`.
4. Each venue passes `not dossier._is_junk_venue(name)` and the new `is_named_kitchen(name)` (section 3).
5. The two venues have different `venue_key()` values. They also have different keys after parentheticals are removed. This removes same-brand rows such as "Slanted Door (Valencia Street)" to "Slanted Door (Ferry Building Marketplace)" (78 today). Those rows are relocations, not chef moves.

Result: one hop is one named person, one quote and one source link.

Decisions and reasons:

- No hop joins two documents. A link such as "chef X is cited at A and at B" needs a person match across articles. A wrong match would invent a connection.
- A displayed move with only one venue is a stint. Stints give a chef an entry point in Connect and feed mentor counts. A stint is never a hop.
- A mentor credit counts only when the move is displayed and the quote contains the mentor's surname (143 of 166 displayed mentor moves today). The strings "null" and "none" are not mentors.
- When two kitchens have more than one hop, the views show the best citation first. Order: quote names both kitchens, then one kitchen; then outlet weight (`dossier.TIER_WEIGHT`); then a move with a year; then source URL as the stable tie-break.
- Tree depth means "moves away", not "trained by". Page text says "within three moves". Page text does not say "influence", "descendants" or "protege" about a tree. A test locks this.

### 3. Identity of kitchens and people

Kitchens:

- Node key: `venue_aliases.identity(name)`, reached as `dossier.venue_key()`. This is the same key that `stats()` counts and that the index stamps as `from_venue_key` and `to_venue_key`. The graph adds no second identity rule.
- The key folds accents, quotes, a leading "The" and a street address in parentheses. It applies the owner's rulings in `ui/venue_aliases.json`: `merge` joins spellings, `locations` keeps cities apart (Stars in Seattle is not Stars in San Francisco).
- Display name: the canonical title from the `merge` table when a ruling exists. If not, the star-list name for a starred kitchen. If not, the most-cited spelling, with a digit-led parenthetical removed.
- Share slug: the builder makes a readable slug from the display name. It keeps the slug only if `venue_key(slug)` returns the node key. If not, the slug is the node key. 17 of 2,156 names need this fallback today. Pages take slugs from payloads and never compute them.
- New rule `is_named_kitchen(name)` in `src/graph_build.py`. It rejects a name that starts with an article or possessive ("a restaurant in Marin County", "his own restaurant"), starts with "unnamed", has no capital letter or digit ("luxury yachts"), is a list of three or more venues, is only a street address ("252 California St."), or is a show or event ("Top Chef"). About 3% of the venue strings in hops fail. `_is_junk_venue` does not change.
- Stars: `ui/city_venues.json` rows with `michelin: true`. The join uses `venue_key(lineage_name)` and `venue_key(star_name)`. `lineage_name` is necessary: the guide says "Naides", the record says "Restaurant Naides". The list is San Francisco only (see section 19).
- Booking: a node gets booking links only from `dossier.dossier_booking(display_name)`. That lookup uses `_booking_key`, which does not apply alias merges. If two spellings of one node have different verified pages, the node shows no booking link. `dispatch()` adds booking at request time, so a new `ui/dossier_booking.json` needs no graph rebuild.

Name groups that differ only by a parenthetical (owner decision: draft rulings for review):

- 93 groups today, for example "Quince", "Quince (current location)", "Quince (original location)". They are 214 separate nodes and touch 381 displayed moves.
- The second pull request adds drafted rulings to `ui/venue_aliases.json`. The owner reviews them in the diff.
- Rule for the draft: the same room, or a relocation inside one city, becomes `merge`. A branch in another city becomes `locations`.
- The pull request description lists each group with its spellings, its move counts and the drafted ruling. A group that the rule does not decide stays as it is and is listed as "not ruled".
- The builder writes the candidate groups to `crawl/graph_identity_review.json`, so the list can be made again after each corpus update.
- Effect: the kitchen count from `/api/stats` falls by the number of merged names. That is correct and expected.

People:

- The builder runs `dossier.identity()` once over all kept moves. This is the same clustering that a dossier shows. Today: 1,538 people, 88 of them with the `homonym` flag.
- Person id: a slug of the cluster key (`norm_name`). When one key has more than one cluster, the id gets `~2`, `~3` in order of move count. The two clusters stay separate people.
- `alumni` for a kitchen is the number of person clusters that `dossier.identity()` returns for the hops out of that kitchen. It counts people, not moves.
- A chef that carries the `homonym` flag shows "possibly two people" in pickers and on hops, as the dossier does.
- `identity()` takes 1.4 s on today's displayed moves and more after the gate fix. That is the main reason the clustering runs at build time and not in a cold function.

### 4. How the graph is served: a committed graph file

| | Graph file in the bundle (chosen) | Load from Elasticsearch on a cold function |
|---|---|---|
| Cold cost | 6 ms to parse, 3 ms to index (measured on a 1.1 MB prototype; about 2 MB after the gate fix) | 0.6 s for two search pages of 6 MB, then the gate and 1.4 s or more for `identity()`. About 2 s or more for each cold instance, from region iad1 to us-central1 |
| Elasticsearch down | Tree, Connect and Ledger still work | All showpiece views fail. The README records one outage of this kind |
| Freshness | Stale until the script runs again. The file states its build date | Fresh at each cold start, then stale for the cache time |
| Bundle size | About 2 MB more. `ui/city_venues.json` is already 1.7 MB. The Python limit is 500 MB | No change |
| Review | A corpus update shows as a diff. Tests run on real data with no credentials | No offline check is possible |
| Precedent | `ui/score_sample.json`, `ui/venue_booking.json`, `ui/dossier_booking.json` | none |
| Two runtimes | `ui/server.py` and the Vercel function read the same file through `dossier.data_path()`. The local demo and the deploy show the same graph | Each runtime holds its own cached copy, built at a different time |

Decision: build the file at corpus-update time and commit it. Do not build it in `vercel-app/build.sh`, because a deploy must not depend on Elasticsearch.

File: `ui/graph.json` (compact JSON, UTF-8, sorted so that two builds from the same index are byte-identical except `built_at`).

```json
{
  "v": 1,
  "built_at": "2026-11-27",
  "summary": {
    "source_moves": 9312, "gate_passed": 0, "moves_kept": 0,
    "hops": 0, "kitchens_linked": 0, "largest_set": 0,
    "people": 0, "homonym_flags": 0, "mentor_moves": 0, "published_at": 0,
    "dropped": {"gate": 0, "unnamed_person": 0, "unnamed_kitchen": 0, "junk_kitchen": 0, "same_brand": 0},
    "starred": {"source": "Michelin Guide 2026, San Francisco", "total": 26,
                "with_move": 0, "linked": 0, "missing": ["..."]},
    "bay_area": {"moves": 0, "towns": [["Oakland", 0]], "kitchens_placed_sf": 0,
                 "anchors": [{"name": "The French Laundry", "slug": "french-laundry", "town": "Yountville",
                              "moves": 0, "quotes_naming_town": 0}]}
  },
  "kitchens": [["frenchlaundry", "The French Laundry", "french-laundry", 0, []]],
  "people":   [["thomas-keller", "Thomas Keller", 0]],
  "moves":    [[0, 0, 12, "pastry chef", null, "eater", "https://...", "full quotation", null, "high", "JOINED", 2, "move"]]
}
```

- The zero values are slots that the script fills. Section 11 gives today's measured values for `bay_area`.
- `kitchens` row: key, display name, slug, stars (0 to 3), other spellings.
- `people` row: id, display name, homonym flag.
- `moves` row: person index, from index or -1, to index or -1, role, year, outlet (`dossier.outlet_tier`), source URL, quotation, mentor, confidence, action, quote score (2, 1 or 0 kitchens named), and the result of `citation_reason`.
- The file keeps the full quotation. A test can then run `citation_supported` on every shipped move. Responses cut the quotation to 220 characters, as `assemble_dossier` does.

Builder:

- `src/graph_build.py` (not shipped to the function): `build(edges, starred_rows, alias_data, hood_maps) -> dict`. It is a pure function. It imports `citation_reason`, `_is_collective`, `_is_junk_venue`, `venue_key`, `identity` and `outlet_tier` from `src.dossier`, so the gate has one implementation.
- `scripts/build_graph.py`: reads all moves with `search_after` pages of 5,000 (two requests today), calls `build()`, writes `ui/graph.json` through a temporary file. It follows the pattern of `scripts/stamp_score_sample.py`.
- `scripts/build_graph.py --check`: rebuilds in memory and compares with the committed file, without `built_at`. Exit code 1 means the file is stale.
- The README "Build the corpus" section lists the script after `grow_corpus.py`, with `stamp_score_sample.py`.

Freshness shown to the reader: `/api/numbers` returns the build date and `source_moves` from the file, and the live move count. When they differ, the Numbers page says so in plain text.

### 5. `src/graph.py` and the new endpoints

`src/graph.py` is stdlib only. It imports only `.venue_aliases`. It does not import `dossier`. `dossier.py` imports it with `from .graph import ...` and loads the file with `data_path("graph.json")`, so `tests/test_shared_core.py` forces `build.sh` to ship both.

- `load(path)`: parses the file once for each warm instance. It builds out-links, in-links, an undirected link set, connected-set ids, and name indexes.
- `tree(g, name, depth, direction)`, `connect(g, a, b)`, `ledger(g)`, `nodes(g, q, kind, limit, near)`, `summary(g)`. `ledger` and `summary` are memoized.
- The tree is a breadth-first tree. Each kitchen is in the tree once, at its smallest depth. The parent is the first one in key order. `reach` is the node count of that tree, so the headline figure and the drawing cannot differ.

In `dispatch()`, the graph endpoints run before `es = client()`, like `venues`. The function then never imports the `elasticsearch` package for them.

Common rules: GET only. Text parameters are cut at `MAX_QUERY_LEN` (120). A bad number becomes the default, never a 500. An unknown name returns 200 with `resolved: false`, as `/api/search` does.

| Endpoint | Parameters | Limits | Rate limit for each IP | Cache-Control |
|---|---|---|---|---|
| `/api/tree` | `k` name or slug; `depth` 1 to 3, default 3; `dir` `down` or `up`, default `down` | at most 300 nodes; `truncated` flag; totals are computed before the cut | bucket `graph`, 60 in 60 s | `public, max-age=300, s-maxage=86400, stale-while-revalidate=604800` |
| `/api/connect` | `a`, `b`: kitchen name or slug, or `chef:<person id or name>` | one shortest chain; at most 3 citations for each hop | bucket `graph` | same |
| `/api/ledger` | none | kitchens with 3 or more alumni; 25 mentors; 26 starred rows | bucket `graph` | same |
| `/api/nodes` | `q` (2 or more characters); `kind` `kitchen`, `chef` or `any`; `near` node id; `limit` 1 to 12, default 8 | name match on folded word prefixes; order by match quality, then hop count | bucket `nodes`, 120 in 60 s | same |
| `/api/numbers` | none | - | bucket `numbers`, 30 in 60 s | `public, max-age=60, s-maxage=300, stale-while-revalidate=3600`; `no-store` when the live part failed |

The node limit is 300 because the estimate for the largest tree after the gate fix is 180 to 210 nodes at three moves.

`_LIMITS` in `dossier.py` gains the entries `tree`, `connect`, `ledger`, `nodes` and `numbers`, so the existing check at the top of `dispatch()` applies them.

The Vercel CDN caches a function response that carries `s-maxage`. The cache key contains the deployment URL and the query string. Each deploy starts with an empty cache, so a new graph file is never served from an old cache. Rate limits stay in memory for each instance (`allow_request`), as today.

In the JSON examples below, the values show the shape only.

`GET /api/tree?k=french-laundry`

```json
{
  "resolved": true, "direction": "down", "built_at": "2026-11-27",
  "root": {"id": "frenchlaundry", "name": "The French Laundry", "slug": "french-laundry", "stars": 0, "booking": null},
  "summary": {"alumni": 16, "generations": [16, 22, 22], "reach": 60, "starred": 6,
              "starred_names": ["Angler", "Benu"], "depth": 3, "truncated": false, "other_direction": 0},
  "children": [
    {"id": "quince", "name": "Quince", "slug": "quince", "stars": 3, "booking": {"resy": "https://..."},
     "gen": 1, "below": 9,
     "via": [{"person": "Devin McDavid", "person_id": "devin-mcdavid", "homonym": false,
              "role": "pastry chef", "year": null, "outlet": "eater", "confidence": "high",
              "source_url": "https://...", "evidence": "Michael Tusk has hired new pastry chef Devin McDavid ..."}],
     "more_via": 0,
     "children": []}
  ]
}
```

- `dir=up` follows hops in reverse. It answers "where did this kitchen's people come from". The payload shape is the same.
- A kitchen with no hop in the asked direction returns `resolved: true`, empty `children` and `other_direction` so the page can offer the other view.
- Unresolved: `{"resolved": false, "query": "...", "suggestions": [node, ...]}`.

`GET /api/connect?a=french-laundry&b=mister-jius`

```json
{
  "resolved": true, "found": true, "length": 2,
  "a": {"kind": "kitchen", "id": "frenchlaundry", "name": "The French Laundry", "slug": "french-laundry", "stars": 0},
  "b": {"kind": "kitchen", "id": "misterjius", "name": "Mister Jiu's", "slug": "mister-jius", "stars": 1},
  "hops": [
    {"from": {"id": "frenchlaundry", "name": "The French Laundry", "stars": 0},
     "to": {"id": "quince", "name": "Quince", "stars": 3},
     "direction": "forward",
     "via": [{"person": "Devin McDavid", "role": "pastry chef", "year": null, "outlet": "eater",
              "source_url": "https://...", "evidence": "..."}],
     "more_via": 0}
  ],
  "also": null
}
```

- The search is breadth-first on the undirected link set. Neighbours are visited in key order, so the same pair always returns the same chain.
- `direction` is `forward` when the cited person moved from `from` to `to`, and `reverse` when the cited move ran the other way.
- A chef end point starts from every kitchen in that chef's kept moves. The first or last row is then a stint row: `{"stint": true, "person": ..., "kitchen": ..., "via": [...]}`.
- A plain name resolves to a kitchen first. If a chef has the same name ("Michael Mina"), `also` carries the chef node so the page can offer it.
- Not found: `{"resolved": true, "found": false, "reason": "no_chain", "a_set": 631, "b_set": 3}`. Other reasons: `unknown_a`, `unknown_b`, `same`.

`GET /api/ledger`

```json
{
  "built_at": "2026-11-27",
  "featured": {"tree": "french-laundry",
               "pairs": [{"a": "french-laundry", "b": "mister-jius", "length": 2}]},
  "leaders": {"alumni": {"slug": "chez-panisse", "name": "Chez Panisse", "value": 21},
              "reach": {}, "starred_within": {}, "mentor": {"name": "Thomas Keller", "value": 5}},
  "kitchens": [{"kitchen": {"id": "chezpanisse", "name": "Chez Panisse", "slug": "chez-panisse", "stars": 0},
                "alumni": 21, "kitchens": 19, "reach": 37, "starred": 0, "starred_names": []}],
  "mentors": [{"mentor": "Thomas Keller", "chefs": 5, "moves": 12,
               "sample": [{"person": "...", "evidence": "...", "source_url": "https://..."}]}],
  "starred": [{"kitchen": {"name": "Benu", "slug": "benu", "stars": 3}, "arrivals": 2,
               "from": [{"name": "...", "slug": "..."}], "alumni": 7, "status": "linked"}],
  "rules": {"min_alumni": 3, "mentor_min_chefs": 2, "depth": 3, "mentor_moves": 0}
}
```

- `kitchens` holds every kitchen with 3 or more alumni (77 today; about 140 to 155 after the gate fix). The page sorts this one list by `alumni`, `reach` or `starred`. Without the 3-alumni rule a kitchen with one alumnus and one busy child ranks near the top for reach.
- Ties sort by the next figure, then by name.
- `leaders` gives the four record holders that the mockup shows above the table.
- `starred` lists all 26 rows. `status` is `linked`, `move_only` or `none`.
- `featured.tree` is the kitchen with the most starred kitchens within three moves. `featured.pairs` holds up to four pairs: the top kitchens by alumni, each with its highest-starred kitchen at 2 to 4 moves. The landing page and the Connect page use them, so their examples are always true after a corpus update.

`GET /api/nodes?q=quin&kind=kitchen&near=frenchlaundry`

```json
{"query": "quin", "nodes": [{"kind": "kitchen", "id": "quince", "name": "Quince", "slug": "quince",
  "stars": 3, "hops": 24, "has_tree": true, "joined": true, "note": null}]}
```

- `joined` is present when `near` is set. It is true when the two nodes are in the same connected set.
- A chef row has `note` with up to two kitchens, for example "Quince, Mister Jiu's".
- The new pages use this endpoint, not `/api/suggest`. Every suggestion is then a node that resolves.

`GET /api/numbers`: see section 11.

Routes and adapters:

- `vercel-app/vercel.json`: add rewrites for `/api/tree`, `/api/connect`, `/api/ledger`, `/api/nodes`, `/api/numbers` to `/api/search`.
- `vercel-app/api/search.py` and `ui/server.py` do not change for the API. Both already pass every `/api/*` path to `dispatch()`.

### 6. Pages, routes and what the build ships

New files in `ui/`: `tree.html`, `connect.html`, `ledger.html`, `numbers.html`, `lineage.js`, `graph.json`, `gate_stamp.json`, `og.png`. Rebuilt: `landing.html`. Changed: `explorer.html`, `method.html`.

Why new pages and not more of `explorer.html`:

- `explorer.html` is 1,848 lines and 106 KB. It loads Mapbox GL, which needs WebGL. The showpiece views must work without WebGL.
- The explorer rail is about 360 px wide. A tree needs the full width.
- `tests/test_explorer_ux.py` locks many explorer details. New pages keep that risk away.
- Each view gets its own short URL to share, and each pull request stays small.

Why one shared script: the tree layout, the chain renderer, the citation card and the picker are used by three pages. `ui/lineage.js` is a plain script loaded with `<script src="/lineage.js" defer>`. `ui/map.js` is the precedent for a separate plain script. It exposes one global, `window.Lineage`, with `esc`, `fmt`, `citeCard`, `picker`, `layoutTree`, `renderTree`, `renderTreeList` and `renderLine`. Page-specific code stays inline in each page.

Routes:

| Route | File | `vercel.json` rewrite | `ui/server.py` `PAGES` |
|---|---|---|---|
| `/tree` | `tree.html` | `/tree` to `/tree.html` | `/tree`, `/tree.html` |
| `/connect` | `connect.html` | `/connect` to `/connect.html` | `/connect`, `/connect.html` |
| `/ledger` | `ledger.html` | `/ledger` to `/ledger.html` | `/ledger`, `/ledger.html` |
| `/numbers` | `numbers.html` | `/numbers` to `/numbers.html` | `/numbers`, `/numbers.html` |

`vercel-app/build.sh` adds:

- to `public/`: the four new pages, `lineage.js`, `og.png`;
- to `api/_lib/`: `src/graph.py`, `ui/graph.json` and `ui/gate_stamp.json`.

`ui/server.py` already serves any other file in `ui/` as a static file, so `/lineage.js` and `/og.png` need no code there.

URL state: `/tree?k=<slug>&dir=up&view=list` and `/connect?a=<slug>&b=<slug>`. A page writes its state with `history.pushState` for a new root or pair, and handles `popstate`. A reload of the URL shows the same view. "Copy link" copies `location.href`. The page calls `navigator.share` when the browser has it.

Safety: all names and quotations come from scraped articles. The renderers write them with `textContent` or `esc()`. A source or booking link is rendered only when it starts with `https://` or `http://`.

### 7. One header on all pages, with no build step

- The header and footer markup must be in each HTML file. Markup that a script adds would flash and would fail without JavaScript.
- The canonical copy is `ui/_chrome.html`. It holds four marked blocks: the chrome CSS, the header, the footer, and the menu script.
- Each page holds the same four blocks between markers: `/* bf:chrome */`, `<!-- bf:header -->`, `<!-- bf:footer -->` and `<!-- bf:chrome-js -->`, each with its closing marker.
- `scripts/sync_chrome.py` copies the blocks from `ui/_chrome.html` into the seven pages. It is a developer tool. Its output is committed. The deploy does not run it.
- `tests/test_chrome.py` fails when a block in a page differs from `ui/_chrome.html`. The only permitted difference is `aria-current="page"` on that page's own link, which the script sets.
- `build.sh` does not copy `_chrome.html`.

Header structure, from the mockups (`views-nav-phone-menu-open.html` and the header on each desktop mockup):

- a "Skip to content" link as the first focusable element, with a `main` target on every page;
- a bar 60 px high: the wordmark as a link to `/`; then Explore, Trees, Connect, Ledger; then Method and Numbers at the right;
- the links are in one `<nav aria-label="Site">`;
- the current page has `aria-current="page"` and the terracotta rule on the header hairline.

Phone menu:

- At 760 px and narrower the links fold behind a "Menu" button.
- The button is in the markup with the `hidden` attribute. The menu script, about 15 lines, removes `hidden`, collapses the nav and sets `aria-expanded` and `aria-controls`.
- The script toggles the menu, closes it on Escape, and returns focus to the button.
- Without JavaScript the button stays hidden and the links show as a wrapped block under the wordmark. All links stay reachable.
- A menu row has a hit area of 44 px or more.

The chrome CSS uses only the tokens in `docs/DESIGN.md`. It reuses the `.wordmark` rule and the focus ring (2 px `--accent`, offset 3 px).

The explorer is a full-height application. Its `.app` grid height becomes the viewport height minus the header height. The rail's `h1` wordmark becomes a visually hidden `h1` with the text "Explorer", so the wordmark is on the page once.

### 8. The Tree view

Data: one call to `/api/tree`. The picker calls `/api/nodes?kind=kitchen`.

Drawing:

- `Lineage.layoutTree(tree, mode)` is a pure function. It returns node positions and link paths. The mockups give two modes: "rings" (recommended by the design agent) and "descent". The owner's choice sets the default. The other mode needs no other change.
- Rings: the root at the centre. The first and second moves are on two rings with labels. The third move is an outer ring with one mark for each kitchen and no label. The reader sees the reach before reading it.
- Descent: one column for each generation, with the person on each row.
- `Lineage.renderTree` writes one inline `<svg>`. A node is an SVG `<a>` with a mark, a `<text>` label and a star mark. The SVG is drawn at 1:1. There is no pan, zoom or canvas.

How a large tree stays legible (estimate after the gate fix: the French Laundry tree has about 20, 50 and 85 kitchens on its three rings; the largest tree has about 200):

- The server sends at most 300 nodes.
- Ring one always has labels. Ring two has labels when it has 40 kitchens or fewer. Above 40, ring two labels only starred kitchens and the selected branch.
- Ring three has marks only. A mark has a `<title>` and an accessible name, and it opens the citation panel as a labelled node does.
- In descent mode a parent shows at most 8 children. The rest are behind "+N more kitchens".
- Children sort by: starred first, then `below` (kitchens under that branch), then name.
- A label is at least 12.5 px and is never scaled down. A name longer than 26 characters is cut with an ellipsis; the full name is in `<title>` and in the citation panel.
- A branch line uses `--dim` (5.8:1 on `--bg`). `--faint` is for hairlines only; it is below 3:1 and must not carry a branch. A route to a starred kitchen uses `--gold`. The selected branch uses `--ink`.
- A star is a text mark and part of the accessible name. Colour alone never carries it. The legend says: "Stars: Michelin Guide 2026, San Francisco kitchens only."
- The legend also says that rings follow cited moves, not dates, and gives the share of moves with a year from the payload.
- The list view holds every name. The drawing is allowed to leave ring-three names out because the list does not.

The citation panel is the proof. A click or Enter on a node opens it:

- the kitchen, its stars, and each cited move on that branch: person (link to `/explorer?q=`), role, year when the move has one, the quotation in a `<blockquote>`, the outlet and the source link;
- "possibly two people" when the person has the homonym flag;
- actions: "Open dossier" (`/explorer?q=`), "Grow the tree from here" (`/tree?k=`), "Trace a line from <root>" (`/connect?a=&b=`);
- booking buttons only when the payload has `booking`. They reuse the explorer's `.bookrow` pill style.
- At 900 px and wider the panel is a sticky column at the right. Escape closes it and returns focus to the node.

The summary line above the tree states the figures from `summary`: cited alumni, kitchens within three moves, starred kitchens. It is an `aria-live="polite"` region.

Non-visual equivalent (mockup: the tree list outline):

- `Lineage.renderTreeList` writes the same tree as nested `<ul>` lists. A row has the kitchen link, the star text, "via <person>, <role>", and a `<details>` element with the quotation and the source link.
- Only one of the two views is displayed at a time. The SVG view has `role="group"` and a label. Each SVG node link has an accessible name such as "Quince, three Michelin stars, via Devin McDavid, 1 cited move".
- SVG nodes are in depth-first DOM order, so Tab follows a branch. Focus shows as a 2 px `--accent` stroke on the node.
- A "List" and "Tree" switch (`aria-pressed`) is always available at desktop widths. The choice is kept in the URL (`view=list`).

Reduced motion: the tree may draw in once, in 600 ms or less (opacity and line reveal). Under `prefers-reduced-motion: reduce` there is no animation and no smooth scroll. Scripted motion checks `matchMedia` first.

At 390 px (mockup: the phone tree):

- A small ring emblem shows the scale. It is decorative: `aria-hidden="true"`, with no link and no focusable part.
- Under it: the summary line, a row of branch chips for ring one, then the open branch as a cited list from `Lineage.renderTreeList`.
- Indentation is 14 px for each generation, with a left rule as the branch. A row is 44 px high or more. The citation opens under its row. The page has no horizontal scroll.

`dir=up` uses the same components. The labels change to "came from".

### 9. The Connect view

- Two pickers, a swap button and a "Trace" button. The picker is the ARIA combobox pattern that the explorer search uses (`role="combobox"`, `aria-controls`, `aria-activedescendant`, arrow keys, Escape).
- The second picker sends `near=<first node id>`. Kitchens with `joined: false` come last with the note "no cited chain yet".
- The result is an ordered list. `Lineage.renderLine` writes `<ol class="line">`: a station for each kitchen and a hop card between two stations.
- At 900 px and wider, a chain of 5 hops or fewer is one horizontal line with a card under each link, as in the desktop mockup. A longer chain, and every chain on a phone, reads top to bottom. The markup is the same; only CSS changes.
- An arrow on each link shows the way the person moved. A hop card also says it in words: "Devin McDavid went from The French Laundry to Quince." When `direction` is `reverse`, the sentence still gives the true direction of the move. Then the quotation and the source link. "+N more citations" opens the others.
- The summary line (`aria-live`) says: "2 cited moves join The French Laundry and Mister Jiu's."
- A chef end point adds a stint row: "<chef> is cited at <kitchen>" with its quotation.
- Hops may appear one after the other, 120 ms apart. Not under reduced motion.

States:

- Empty and picking: up to four traced lines to try, from `featured.pairs` of `/api/ledger`. The page shows no stored pair.
- No chain: "No chain of cited moves joins these two kitchens yet." The page gives the size of each connected set from the payload and links to both trees. This state is a feature: the graph makes no link that it cannot cite.
- Unknown name, same kitchen twice, request error with a retry button, a long chain (all hops are shown).

### 10. The Ledger view

One call to `/api/ledger`. The structure follows the ledger mockups.

| Part | Data | Notes |
|---|---|---|
| Record holders | `leaders` | four figures: most alumni, widest reach, most starred kitchens within three moves, most-named mentor |
| Kitchen table | `kitchens` | one `<table>` with a caption; columns: kitchen, alumni, kitchens within three moves, starred within three moves |
| Mentors | `mentors` | ranked by chefs; a row opens its sample quotations in a `<details>` element |
| The starred kitchens | `starred` | all 26; cited arrivals and where they came from; "no cited move yet" where true |

- The table sorts in the page. Each sortable header is a `<button>` inside its `<th>`, and the `<th>` carries `aria-sort`. The sort key is kept in the URL (`sort=reach`).
- On a phone the sort control is a row of chips and each kitchen is a stacked row. The elements keep their table roles.
- The line under the table states the rule from `rules`: kitchens with 3 or more alumni; three moves; stars from the San Francisco list.
- The mentor part states its limit with a figure from `rules.mentor_moves`: how many displayed moves name a mentor.
- The column label is "Starred within three moves". The mockup text "starred descendants" is not used (section 2).
- A kitchen row links to `/tree?k=<slug>`. A starred row links to `/tree?k=<slug>&dir=up`. A second link opens the dossier.
- Figures use tabular numerals. Anchors: `#kitchens`, `#mentors`, `#starred`.

### 11. By the numbers (`/numbers`)

One call to `/api/numbers`:

```json
{
  "live": {"edges": 9312, "people": 3119, "venues": 4412, "sources": 2221,
           "coverage": {"date": 1454, "era_bucket": 1165, "venue_hoods": 3786, "action": 4360, "mentor": 332},
           "tiers": {"eater": 4849, "sfgate": 4425, "sfchronicle": 16, "other": 22}},
  "graph": {"built_at": "...", "source_moves": 9312, "gate_passed": 0, "hops": 0,
            "kitchens_linked": 0, "largest_set": 0, "people": 0, "homonym_flags": 0,
            "published_at": 0, "starred": {}, "bay_area": {}},
  "gate": {"measured_at": "...", "sample_n": 400, "sample_true": 0, "precision": 0.0, "precision_low": 0.0,
           "baseline_n": 200, "baseline_true": 0, "both_share": 0.0},
  "booking": {"map_pins": 222, "dossier_names": 272, "graph_kitchens": 0},
  "map": {"pins": 4728},
  "fresh": true
}
```

`dossier._numbers(client)` builds it. `live` comes from the existing `method(es)`, which already calls `stats(es)`; both keep their 300 s cache. `gate` comes from `ui/gate_stamp.json`. If Elasticsearch fails, `live` is `null`, `fresh` is `null`, the status is 200 and the response is not cached. The `live` values in the example are today's measured values. The zero values are slots.

| Figure on the page | Computed from | Kind |
|---|---|---|
| Moves on record | `stats()`: `es.count` on `bone-fides-edges` | live |
| People named | `stats()`: cardinality of `person.keyword` | live |
| Kitchen names | `stats()`: distinct `venue_key()` of `from_venue` and `to_venue`, junk removed | live |
| Articles cited | `stats()`: cardinality of `source_url.keyword` | live |
| Moves with a date, a usable year, a neighbourhood, a typed action, a named mentor | `method()`: `exists` filters on `date`, `era_bucket`, `venue_hoods`, `action`, `mentor` | live |
| Outlet mix | `method()`: `outlet_tier()` on `source` and the URL host | live |
| Moves displayed after the gate | `summary.gate_passed` of `summary.source_moves` | graph file, with its date |
| Precision of the displayed moves | `gate`: true rows of the labelled sample, sample size, lower bound, date; the baseline figure | gate stamp, with its date |
| Moves that link two named kitchens | `summary.hops` | graph file |
| Kitchens linked; largest connected set | `summary.kitchens_linked`, `summary.largest_set` | graph file |
| People after disambiguation; "possibly two people" flags | `summary.people`, `summary.homonym_flags` | graph file |
| Starred kitchens: listed, with a displayed move, linked, and the names with none | `summary.starred` | graph file |
| Bay Area reach (see below) | `summary.bay_area` | graph file |
| Verified booking pages | key counts of `venue_booking.json` and `dossier_booking.json`; graph kitchens for which `dossier_booking()` returns links | bundled files, at request time |
| Map pins | `len(venues_geo())` | bundled files, at request time |
| Articles with a publication date | `summary.published_at` | graph file |

`fresh` is true when `live.edges` equals `graph.source_moves`. When it is false the page says: "The graph views were built on <date> from <n> moves. The index now holds <m>."

The next market: the Bay Area (owner decision). The page says that the record already reaches the wider Bay Area and that the Bay Area is the next step. The supporting figures come from `summary.bay_area`.

- What the data can prove, and the builder computes:
  - `moves`: displayed moves whose quotation names a Bay Area town outside San Francisco. Today: 541 of 3,388. The town list is the constant `BAY_AREA_TOWNS` in `src/graph_build.py` (28 towns). "Richmond" is not in it, because it is also a San Francisco district.
  - `towns`: the same count for each town. On all moves on record today: Oakland 289, Napa 170, Berkeley 131, St. Helena 75, Palo Alto 69, Yountville 66.
  - `anchors`: The French Laundry (Yountville), Chez Panisse (Berkeley) and Manresa (Los Gatos). For each: its displayed moves, and the number of them whose quotation names the town. Today: 46 and 9; 50 and 5; 39 and 5. The page shows an anchor only when `quotes_naming_town` is 1 or more, so the town is traceable to a quotation.
- What the data cannot prove: the number of linked kitchens outside San Francisco. The record holds no location for a kitchen. The city permit file (`src/hoods.py` `hood_for`) places 341 of today's 1,587 linked kitchens in San Francisco. The others, about 1,250, are closed San Francisco kitchens, Bay Area kitchens and kitchens elsewhere. The data cannot split them.
- The page states this limit in one sentence with `kitchens_placed_sf`. It gives no count of kitchens outside San Francisco.
- The page also states what a new market needs, from the repository: a source list (`READING-LIST.md` and the queries in `scripts/grow_corpus.py`), the permit file of each city (`scripts/pull_city.py`), and the star list (`src/tag_city.py`). It gives no date.

Honest gaps the page states, each with its figure from the payload:

1. A large share of the moves on record is not displayed, because the quote does not state the move.
2. The precision of the displayed moves is a sample measurement. The page gives the sample size, the date and the lower bound.
3. Dates are thin: 15.6% of moves have a date and 12.5% a usable year. The site makes no timeline claim.
4. Two outlets supply nearly all moves (Eater and SFGate, 99.6% today).
5. Some starred kitchens have no displayed move. The page names them.
6. About half of the linked kitchens are not in the main connected set.
7. No record carries an article publication date yet. The page shows no growth chart.
8. Booking covers a small share of map pins.
9. The record holds no location for a kitchen, and the star list covers San Francisco only.

Sections (mockup: the numbers report): the record; the gate (the funnel from moves on record to linked kitchens, the measured precision, and why each figure is traceable to a quotation); sources; coverage and gaps; booking; the Bay Area; contact.

Rules for the text:

- The page has no user, customer, revenue, partner or growth-rate figure, and no words that imply one. A test forbids "customers", "revenue", "users", "traction", "trusted by", "clients".
- Each figure is a `data-fig` slot that shows an em dash until the payload arrives. If the request fails, the page says the figures are not available. It never shows a stored figure.
- Contact (owner decision): one link, `mailto:patrick@boxfordpartners.com`.

### 12. The landing page

Order of sections: shared header; hero; three feature blocks (Tree, Connect, Ledger); proof; the consumer loop; footer.

- Hero: the mockups give two directions. The tree hero draws the tree of `featured.tree` at two moves. The line hero draws the chain of `featured.pairs[0]`. Both use `Lineage` renderers and live payloads. The owner's choice sets which one is the hero; the other one is the Connect or Tree feature block.
- A line under the hero gives its figures from the payload. Two actions: "Open the tree" and "Trace a line".
- Ledger block: the record holders from `leaders`.
- Proof (owner decision): `n-edges` has the label "Moves on record". The displayed count is beside it, from `/api/numbers` (`graph.gate_passed`), with the measured precision. The other three counts stay.
- The slots keep the ids `n-edges`, `n-people`, `n-venues`, `n-sources`, and the script keeps the `getElementById('<id>')` calls. `tests/test_shared_core.py` requires both. Links to `/method` and `/numbers`.
- Consumer loop: explore (tree), trust (quotation and source), book (verified pages only), with a link to the explorer.

Requests: `/api/ledger`, then `/api/tree` and `/api/connect` for the featured names, `/api/stats` and `/api/numbers`. The graph requests come from the CDN cache after the first visitor.

With no JavaScript or a failed request, the hero shows the headline, the text and the two actions. Figure slots show an em dash. The hero reserves the height of the drawing, so the layout does not shift.

### 13. Changes to the existing pages

- `explorer.html`: the shared header. For a kitchen dossier, two links in the dossier header: "Family tree" (`/tree?k=`) and "Trace a line" (`/connect?a=`). `/api/search` adds `graph: {"id", "slug", "has_tree", "joined"}` to a resolved kitchen payload; `dispatch()` reads it from the graph file with no Elasticsearch call. The page shows the links only when `graph` is present. The "View as tree" switch in the rail does not change.
- `method.html`: the gate block of section 1.9 arrives with the gate fix. Later: the shared header, a link to `/numbers`, and one corrected sentence. The page says the corpus has no venue identity table, but `ui/venue_aliases.json` is that table. `test_method_page_explains_kitchen_names_are_not_restaurants` locks the old text and is updated with it.
- `README.md`: the status note says Elasticsearch is gone. It is live: `/api/stats` returned 200 with 9,312 moves on 2026-11-25. The note is removed. The new scripts and pages are added.
- `docs/DESIGN.md`: a short section for the header, the tree node, the line and the rule that branch lines use `--dim`.

The consumer loop is closed in each view: a tree node and a chain station each lead to the quotation, the source, the dossier and, when verified, the booking page.

### 14. Share images

- A share image for each tree needs a PNG with drawn text. The Python standard library cannot draw text. The options are Pillow and a font file in the function, a Node function with `@vercel/og`, or images made offline with a headless browser. Each one breaks the stack rule or adds a new pipeline.
- A crawler does not run JavaScript. A title or image for each tree also needs HTML from the server for `/tree`. That puts a cold Python function in front of a page that is static today.
- A card that states a reach figure becomes false when the graph changes, unless the same script run makes the card again.
- Decision: no image for each tree or dossier in this release. The share-card mockup (`views-tree-share-card.html`) is the design for that later work.
- This release ships: static `og:title`, `og:description` and `twitter:card` tags on each page, and one brand card `ui/og.png` (1200 by 630). The card uses the ring drawing, the wordmark and the tagline from the mockup. It has no kitchen name and no figure, so it cannot become false. Its absolute URL uses the production host.
- Sharing works by link: each tree and each chain has a URL that shows the same view again.
- Later route, not planned here: `scripts/build_graph.py` renders a card for each ledger kitchen with a headless browser in the same run, and stores the cards in the Vercel Blob store that holds the venue photos. A rewrite with a user-agent condition serves crawler HTML.

### 15. UI brief: bonefides-flagship

One theme (warm-dark, `docs/DESIGN.md`). Widths: 1440 px and 390 px, plus the app's own switches at 900 px, 760 px and 640 px.

Mockups in `docs/flagship/mockups/` set the look. Views: tree rings, tree descent, tree list, tree phone, connect pick and result, ledger, share card, header with phone menu (`design-plan-views.json`). Front: landing with two hero directions, and the numbers report. The mockups use the gated prototype figures of the data brief. The built views take every name and figure from the API, so the mockup figures change after the gate fix.

Component map:

- Shared header, phone menu and footer → new: `sitehead`, `menubtn`, `menu`, built from `.wordmark` and the nav link values of `method.html`
- Skip link → new: `bf-skip` (focus ring token)
- Kicker, section head, lede, call to action → existing `.kicker`, `.shead`, `.lede`, `.cta` of `landing.html`
- Figure block → existing `.stats` and `.stat` of `landing.html`; `.cov` of `method.html` for coverage figures
- Gap note → existing `.callout` of `method.html`
- Picker → existing `.searchbar` and `.sugg` combobox of `explorer.html`
- Kitchen chip → existing `.vchip`; "Try" lines and branch chips → existing `.chip`
- Booking buttons → existing `.bookrow` pills
- Source badge and confidence dot → existing `.srcbadge`, `.tconf`
- Tree node, branch, ring mark, star mark → new: `tnode`, `tlink`, `tick`, `starglyph`, an extension of the explorer `.tree` SVG chips
- Tree list → extends the explorer `.treelist` rows to nested lists
- Citation panel and hop card → new: `cite`, built from the dossier row parts (quotation, source badge, role)
- Chain → new: `line`, built from the explorer timeline spine
- Ledger table and record holders → new: `ltable`; record holders reuse `.stat`
- Gate block on the method page → existing `.cov` and `.callout`

State matrix:

- loading → applies (text placeholder, `aria-busy`; figure slots show an em dash)
- empty → applies (Tree and Connect before a choice: featured names from the API)
- error and retry → applies (retry button; no stored figure is shown)
- partial → applies (tree cut at 300 nodes; `live: null` on Numbers; `gate: null` on Method and Numbers; a node with no booking shows no button)
- unresolved name → applies (suggestions from the payload)
- no branches, no chain → applies (sections 8 and 9)
- one item and many → applies (1 to about 30 children; 1 to 12 hops; 1 to 3 citations for a hop; a ring of 1 to about 115 marks)
- long text → applies (long kitchen names, long quotations cut at 220 characters)
- hover, focus-visible, pressed → applies (nodes, rows, pickers, switches, sort buttons, menu button)
- narrow and wide → applies (390 px, 1440 px)
- reduced motion → applies (no draw-in, no smooth scroll)
- no JavaScript → applies to the header only (links stay visible; the menu button stays hidden)
- disabled or no permission → N/A (no accounts; "Trace" is inactive until two names are set, and says why)
- in-flight and after success → applies (a late response for an old request must not replace a newer one; the pages use a request counter as the explorer does)
- destructive actions, live updates → N/A (read-only pages)
- themes → one theme

Verification list: warm-dark × {1440, 390} × {landing: loaded, API failed} × {tree: featured kitchen, the largest tree, kitchen with one branch, no branches, unresolved, list view, `dir=up`} × {connect: empty, 2-hop chain, long chain, no chain, chef end point} × {ledger: each sort key} × {numbers: loaded, `live` null, not fresh} × {method: gate block loaded, `gate` null} × {header on all seven pages; phone menu closed and open}.

Not changed: the Mapbox map and its popups, the dossier layout, the score formula, the rail tree switch, `/api/suggest`, the tips flow, the photo pipeline, all tokens.

### 16. Tests

Unit tests run with no Elasticsearch and no network. Run them as the README says: `.venv/bin/python -m pytest -q`.

`tests/test_citation_gate.py` (the gate fix):

- The owner's five examples pass, each as a real row: "chef-owner -- and eight year veteran of the French Laundry -- Corey Lee"; "Chef Gregory Short, the French Laundry vet who has been in the Masa's kitchen since 2004"; "who was last at the French Laundry"; a "(Cyrus, The French Laundry)" credential list; "Protegé is from two French Laundry veterans".
- Every `must_reject` row of `gate_labels.json` fails: a guest dinner, a pop-up collaboration, a supplier blurb, "inspired by", a recipe sentence, a show as the venue, a promotion with no promotion word, and a quote with a cue that names no venue of the row.
- The anchor rule: accents fold; tokens are whole ("El Faro" does not match "El Farolito"); a one-word generic venue does not anchor.
- The old path is pinned: the pattern sources of `_MOVE_CUE`, `_PROMO_CUE` and `_NONCAREER` equal a hash in the test. Every baseline row returns `"move"` or `"promotion"` from `citation_reason`.
- The proof is recomputed from `gate_labels.json`: the acceptance sample has 400 rows or more; every row has two labels; a row is true only when both are true; precision is 0.95 or more; each family with 30 or more rows is 0.90 or more.
- Every acceptance row is rejected by the old path and accepted by the new one. Every row's `family` equals `citation_reason`.
- `ui/gate_stamp.json` equals the recomputed figures. Its `cue_hash` equals the hash of the pattern sources in `dossier.py`. A later edit of a cue with no new measurement fails here.
- `parse_extraction` admits a row with a new cue and drops a guest-dinner row.
- `method()` returns `gate` from the stamp, and `gate: null` when the file is missing.
- The existing gate tests in `tests/test_review_ee1e.py` and `tests/test_dossier.py` pass with no edit.

Check that needs Elasticsearch: `scripts/measure_gate.py --check` exits 0 (no displayed move lost; samples come again from their seeds; counts equal the stamp).

`tests/test_graph_build.py` (rules, on small hand-made moves):

- the gate: a quotation with no career statement is dropped; `PROMOTED` with no promotion cue is dropped; a guest-chef or supplier quotation is dropped; a cue after character 220 still passes;
- named person: "sous chef" and "a duo of chefs" are dropped;
- `is_named_kitchen`: must-keep and must-drop lists taken from real strings ("Hilda and Jesse", "Sons & Daughters", "The Progress", "mc²" kept; "a restaurant in Marin County", "luxury yachts", "252 California St.", "Town Hall, Salt House, Anchor & Hope", "Top Chef" dropped). `_is_junk_venue` cases are reused;
- identity: "The French Laundry" and "French Laundry" are one node; "Stars (Seattle)" and "Stars (San Francisco)" are two; "Jardinière" and "Jardiniere" are one; a move between two spellings of one kitchen is not a hop; the same-brand rule;
- alias rulings: each drafted `merge` group resolves to one key; each `locations` group keeps its keys apart;
- stars: the join through `lineage_name` finds "Restaurant Naides";
- people: two unconnected bodies of work under one name stay two people with ids `x` and `x~2`; "Jen" and "Jennifer" with a shared kitchen are one;
- mentor credit needs the surname in the quotation; "null" is not a mentor;
- Bay Area: a quotation with "Oakland" counts; "the Richmond" does not; an anchor counts only quotations that name its town;
- slugs: every slug resolves to its own node key;
- two builds of the same input are identical.

`tests/test_graph.py` (logic, on a small fixture graph):

- tree: generations; each kitchen once at its smallest depth; a cycle ends; depth and node limits; totals do not change when the tree is cut; child order; each child has a `via` move from its parent to itself; `dir=up` is the mirror;
- chain: the length equals a brute-force search on 200 random small graphs; each hop's move joins exactly its two kitchens; `direction` is right; chef end points; `unknown_a`, `same`, `no_chain`; the same pair always gives the same chain;
- ledger: alumni counts people, not moves; `reach` equals the node count of `tree()` at depth 3; the 3-alumni rule; tie order; each leader is the top row of its figure; each featured pair has a chain of its stated length;
- nodes: prefix match, accent fold, `joined`, limits.

`tests/test_graph_artifact.py` (honesty, on the committed `ui/graph.json`):

- every move passes `dossier.citation_supported`, has a named person, and has an `http` source URL;
- every kitchen passes `is_named_kitchen` and `not _is_junk_venue`, and its key equals `venue_key(display name)`;
- `summary` equals a new count from the rows;
- `summary.gate_passed` equals `displayed` in `ui/gate_stamp.json` when both files name the same `source_moves`;
- every starred row of `ui/city_venues.json` is a starred node or is in `summary.starred.missing`;
- for every kitchen in the ledger table and for `featured.tree`, an independent breadth-first count written in the test equals `tree().summary` and the ledger row. This is how a showpiece figure is proved and not typed;
- the file is under 4 MB and loads in under 100 ms.

`tests/test_graph_api.py` (through `dispatch()`):

- the four graph endpoints return 200 with a client that raises, as `test_dispatch_routes_and_guards` does for `venues`;
- `/api/numbers` returns 200 with `live: null` and `no-store` when the client raises;
- limits: `depth=9` becomes 3; a 500-character name is cut; `limit=99` becomes 12; bad values never return 500;
- `Cache-Control` values; 429 after the rate limit;
- booking on a node equals `dossier_booking(display name)`, and is absent when two spellings disagree;
- `/api/search` adds `graph` only for a resolved kitchen that is a node.

`tests/test_shared_core.py` (additions): `build.sh` ships `graph.py`, `graph.json`, `gate_stamp.json`, `lineage.js` and every page; each endpoint that `dispatch()` handles has a rewrite; `PAGES` and the page rewrites name the same routes; `graph.py` does not import `src` or `dossier`.

`tests/test_chrome.py`: the four chrome blocks in all seven pages equal `ui/_chrome.html`; `aria-current` is on the right link; each page has one `h1`, one `main` and the skip link; the menu button has `hidden` in the markup.

`tests/test_flagship_pages.py` (text checks on the HTML, in the style of `tests/test_explorer_ux.py`):

- visible text of the five new or rebuilt pages has no number of two or more digits except a four-digit year. Figures are `data-fig` slots with an em dash. The same rule applies to the gate block of `method.html`;
- the stale claims are absent: "262", "37 documented", "21 chefs", "All 26";
- forbidden words on `numbers.html` and `landing.html` (section 11); "influence", "descendants" and "trained by" are absent from the tree, chain and ledger text;
- the contact link on `numbers.html` is `mailto:patrick@boxfordpartners.com`;
- the landing label for `n-edges` is "Moves on record";
- each page has a `prefers-reduced-motion` rule; no font size is under 10.5 px; no hex colour is outside the `:root` block;
- pages render booking only from the payload field.

Check that needs Elasticsearch: `scripts/build_graph.py --check` exits 0. It runs before each pull request that changes `ui/graph.json` and at the release check.

Live browser check, by the testing agent, on `ui/server.py` and on the preview deployment, at 1440 px and 390 px:

- Gate fix: three dossiers from the owner's examples show the newly accepted rows (Benu shows Corey Lee from The French Laundry). The method page shows the precision figure from the stamp. A known guest-chef row is still absent.
- Landing: the hero draws; its figures equal the payload.
- Tree: for the featured kitchen, the number of drawn nodes and marks equals `summary.reach` and the number of star marks equals `summary.starred`. A node opens its citation; the source link opens the article. List view, `dir=up`, share link reload, Back and Forward.
- Connect: each featured pair gives the chain in the payload; each hop has a quotation and a working link. No-chain, unknown name and chef states.
- Ledger: each sort key orders the table as the payload figures do; each row opens the right tree; the figures equal the tree summary.
- Numbers: each slot equals `/api/numbers`; the `live: null` state with a wrong `ELASTIC_ENDPOINT` on the local server; the contact link.
- Keyboard only: skip link, header, phone menu, picker, tree nodes, panel, sort buttons, Escape. Focus is always visible.
- JavaScript off: the header links are visible on a phone width.
- Reduced motion emulation: `document.getAnimations()` is empty after load.
- WebGL off: all pages except the explorer map work; the explorer shows its rail.
- 390 px: `document.documentElement.scrollWidth` is not more than the viewport width on every page.
- axe-core run on each page: no serious or critical finding. Computed-style spot checks: text colours resolve to tokens; branch lines resolve to `--dim`, `--gold` or `--ink`.
- Console: no new error or warning.
- Preview deployment: the second request for a graph endpoint has `x-vercel-cache: HIT`.

### 17. What "10/10" means: the acceptance scorecard

Each row is pass or fail. The release is 10/10 when all rows pass.

| Area | Check | Pass when |
|---|---|---|
| Gate | Proof | 95% or more of 400 newly displayed moves are true by two labellers; each cue family is 90% or more; the labelled file is in the repository and the test recomputes the figure |
| Gate | No loss | `scripts/measure_gate.py --check` reports that no move displayed before is lost; the old patterns are pinned by hash |
| Gate | Still rejected | Guest dinners, pop-up collaborations, supplier blurbs and "inspired by" rows in the fixtures all fail the gate |
| Gate | Disclosure | The method page states the measured precision, the sample size, the lower bound, the date and the baseline figure, all from `/api/method` |
| Function | Tree | Any kitchen with a cited move out opens a tree from the picker, a ledger row, the explorer and a shared link |
| Function | Connect | Each featured pair and any two kitchens of the main connected set return a chain; other pairs return the no-chain state |
| Function | Ledger | Record holders, the sortable table, mentors and the starred list load; every row opens a tree or dossier |
| Function | Navigation | The same header is on seven pages; the phone menu works; no dead link; Back and Forward work |
| Honesty | Branches and hops | Every branch and hop shows a person, a quotation and a source link; `test_graph_artifact.py` passes |
| Honesty | Figures | No typed figure in a page; each showpiece figure equals an independent count in a test; the stale claims are absent |
| Honesty | Labels and gaps | "Moves on record" and the displayed count are side by side; Numbers shows the nine gaps with payload figures and the graph date; the Bay Area section gives only provable figures; no customer or revenue wording |
| Honesty | Booking | A booking button appears only when `dossier_booking` has that exact name |
| Performance | Graph endpoints | No Elasticsearch call; warm response under 150 ms; cold response under 1.5 s; CDN hit on the second request |
| Performance | Pages | Each new page and `lineage.js` together are under 120 KB before compression; no library other than the font; layout shift under 0.05; landing largest paint under 2.5 s on a throttled connection; the largest tree draws in under 300 ms |
| Performance | Outage | With Elasticsearch down, Tree, Connect and Ledger work and Numbers shows its gap state |
| Accessibility | Keyboard and focus | Every control is reachable in a sensible order; focus is visible; Escape closes the panel and the menu |
| Accessibility | Non-visual | The list view holds every node and citation of the tree; the chain is an ordered list; the ledger is a table with `aria-sort`; summaries are announced |
| Accessibility | Contrast and motion | Text is 4.5:1 or more; branch lines are 3:1 or more; no motion under reduced motion; axe-core has no serious finding |
| Mobile | 390 px | No horizontal scroll; targets are 44 px or more; tree, chain, ledger and numbers are fully usable; the header works with and without JavaScript |
| Demo flow | Three minutes | Landing hero → open the tree → open a starred kitchen's citation → open the article → trace a line → ledger → numbers. Each step is one or two actions and shows no spinner longer than 1 s on a warm site |

### 18. Release sequence

Five pull requests to `main`. Each one deploys a coherent site. The header lists only routes that exist at that point; `scripts/sync_chrome.py` adds links as pages land.

1. The gate fix, with proof. `citation_reason`, `_CAREER_CUES`, `_NOT_A_STINT` and the anchor rule in `src/dossier.py`; `scripts/measure_gate.py`; `tests/fixtures/gate_labels.json`; `ui/gate_stamp.json`; the new `ui/score_sample.json`; the `gate` field of `/api/method`; the gate block of `method.html`; the landing Betelnut check; `build.sh`; `tests/test_citation_gate.py`. The description gives the precision figures, the 18 scores before and after, and the false and disputed sample rows. The owner reviews the labels here.
2. Graph engine and API. `src/graph_build.py`, `scripts/build_graph.py`, `ui/graph.json`, `src/graph.py`, the five endpoints in `dispatch()`, rewrites, `build.sh`, the drafted rulings in `ui/venue_aliases.json`, and the tests of section 16 that need no page. No visible change except the kitchen count. The preview is checked with `curl`. The owner reviews the rulings here.
3. Shared header, Tree and Connect. `ui/_chrome.html`, `scripts/sync_chrome.py`, `ui/lineage.js`, `tree.html`, `connect.html`, the header on `landing.html`, `explorer.html` and `method.html`, the two explorer links, routes, `tests/test_chrome.py`.
4. Ledger and By the numbers. `ledger.html`, `numbers.html`, the two new header links, the page tests.
5. Landing rebuild and truth pass. `landing.html`, the share tags and `og.png`, the remaining `method.html`, `README.md` and `docs/DESIGN.md` edits, then the full scorecard run with screenshots of each state.

The gate fix is first because every later figure depends on it. `ui/graph.json` is built once, after the gate is final.

### 19. Noticed, not changed

- The lineage score separates well-documented kitchens less after the gate fix. The sample range narrows from 37 to 79 toward about 64 to 79, because corroboration is full at five articles and depth is full at twelve moves. The formula does not change in this release.
- The 122 promotion rows with no promotion word and the 323 rows with a `_NONCAREER` word stay rejected. Some of the second group are true ("started as a pop-up, then opened the restaurant"). A change to that veto is a separate decision.
- The star list is San Francisco only. The French Laundry, Per Se and Manresa show no star. The legend says so.
- The explorer dossier reads a ranked search window of 25 to 40 moves. A tree can show a cited move that the dossier of the same kitchen does not list. The graph file could make dossiers complete; that is a later change.
- `from_venue_key` and `to_venue_key` in the index are stamped at index time. New alias rulings make some stamps old. No reader uses the stamps today.
- `ui/server.py` serves every file in `ui/`, including the JSON data files, on the local demo only.
- `published_at` is empty on all 9,312 records, so no view can show growth over time.
- The method page figure "Cited moves: the whole corpus" has the same label issue as the landing page. The gate block of section 1.9 puts the displayed share beside it.
