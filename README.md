# Bone Fides

**What:** A kitchen-lineage explorer for San Francisco. Type a restaurant, get its bone fides: where this kitchen came from, where its alumni went, with a source on every edge.

**The Betelnut test:** Betelnut closed. Where did its chefs go? Type "Betelnut" → lineage graph of the chefs who filtered into other SF kitchens, each edge backed by a cited article.

**Why it matters to a resident:** You can look up a restaurant's Yelp stars, but you can't look up its kitchen's pedigree. This is spot-checking a kitchen's bone fides — resident-facing, built from public food journalism.

## Stack (per the hackathon brief)

- **Mistral** — structured extraction (article prose → lineage edges) + narrative synthesis (the bone-fides card text)
- **Elasticsearch** — hybrid search: fuzzy keyword on venue/chef names (aliasing hell: "Tartine" vs "Tartine Bakery") + vector search over article text and chef/venue descriptions

## Data strategy (rules-compliant)

- **This afternoon (allowed = "thinking about ideas"):** source list only — bookmarked public articles, no extraction, no dataset.
- **Tonight at the venue (everything that IS the project):** pipeline code, Mistral extraction, Elasticsearch indexing, the dataset materializing from the reading list, live-extraction demo beat.

## Tonight's plan (5:30–7:30 build, 7:30 demos)

| Time | Goal |
|---|---|
| 5:30–6:15 | Project skeleton + Elasticsearch up (local docker or provided cloud) + Mistral key working |
| 6:15–6:45 | Extraction pipeline: article URL → Mistral → edges → ES index. Parallel: Patrick reads sources, feeds links |
| 6:45–7:15 | UI: search box → bone-fides card + lineage graph. Seed data in |
| 7:15–7:30 | Demo rehearsal: Betelnut query, live-extract an Eater article, close with the pitch |
| — | Fallback: if extraction is slow, even ~15 verified edges demo fine |

## Demo beats

1. "Betelnut closed. Where did its chefs go?" → graph appears with cited edges
2. Live extraction: paste an Eater SF chef-shuffle article URL → new edges land in the graph in seconds
3. Pitch: "Every edge has a source. The database starts from journalism and grows from the web."

## Schema

```
Person    { id, name }
Venue     { id, name, neighborhood?, open/closed status }
Edge      { person, from_venue, to_venue, role, date?, source_url, extracted_at }
```
