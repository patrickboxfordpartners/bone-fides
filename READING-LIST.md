# Bone Fides — Source Reading List

Afternoon deliverable per the rules-compliant plan: a list of public articles to feed the extraction pipeline TONIGHT at the venue. Nothing here is extracted, indexed, or turned into a dataset yet.

All sources are public food journalism or public chef bios. No Yelp review data, no proprietary anything.

## The Betelnut spine (demo centerpiece)

| # | Source | What it gives us |
|---|--------|------------------|
| 1 | https://sf.eater.com/2015/9/23/9389543/say-bye-to-betelnut-closing-after-20-years-in-cow-hollow | The closure. Names exec chef Alexander Ong's exit. 20-year run. |
| 2 | https://www.joecontent.net/china-lives-george-chen-north-beach-new-launches-the-road-back | George Chen interview: Betelnut (1995) → 15 restaurants → China Live. Founder lineage thread. |
| 3 | https://www.sfgate.com/restaurants/diningout/article/DINING-OUT-Asian-Cuisine-With-Integrity-and-3020826.php | 1995 opening review — origin point of the venue node. |
| 4 | https://sf.eater.com/2013/3/15/6466079/inside-hutong-the-reborn-betelnut | Betelnut → Hutong reconcept (venue continuity edge). |
| 5 | http://asian-fusion.com/373/chef-alexander-ong | Ong bio: Ritz-Carlton → Betelnut. Inbound edge. |
| 6 | https://www.potatoglory.com/council/alexander-ong | Ong bio confirming Betelnut chef/partner role + Chronicle Rising Star. |
| 7 | https://medium.com/sfcooking/how-a-cook-becomes-a-chef-alex-ong-chef-emeritus-of-betelnut-795c28d6c790 | Ong post-Betelnut: consulting work. Outbound edge. |
| 8 | https://linkedin.com/in/alexander-ong-5039562 | Ong career timeline: Betelnut 2001–2013 → ChefAlexOng LLC → UMass Amherst (2018– ). Public profile. |

**Honest demo note:** Ong's post-Betelnut path leaves SF (UMass Amherst). The Betelnut answer is Chen's thread (Betelnut → China Live, in SF) plus Ong's cited departure — "some lineage leaves the city, and we show you which" is a feature, not a bug.

## Current-scene shuffles (fuel for the live-extraction beat)

| # | Source | What it gives us |
|---|--------|------------------|
| 9 | https://sf.eater.com/openings | Living page. Confirmed: Mike Lanham (Anomaly → Athanor). More edges accumulate weekly. |
| 10 | https://sf.eater.com/maps/best-new-restaurants-san-francisco | Confirmed: Danny Im → Anju (Mission); Carlos Altamirano → Casa Sofia (his Nth restaurant: Mochica, La Costnera family); Susan Dunn → Esme. |
| 11 | https://www.eater.com/2014/6/3/6213943/chef-shuffles | National chef-shuffle format example — proves extraction-friendliness of the genre. |

## Historical chef-shuffle roundups (extraction-friendly, formulaic)

| # | Source | What it gives us |
|---|--------|------------------|
| 12 | https://sf.eater.com/2014/1/16/6295929/chef-shuffle-bonanza-gitane-range-magnolia-more | Alicia Jenish → Gitane; Carlo Espinas moves at Comstock. |
| 13 | https://sf.eater.com/2019/3/25/18281475/niku-steakhouse-sf-new-chef-change-steve-brown-dustin-falcon | Steve Brown out → SD; Dustin Falcon in at Niku. |
| 14 | https://sf.eater.com/2018/6/18/17477158/yoni-levy-out-outer-sunset-outerlands-chef-shuffle | Yoni Levy out at Outerlands. |
| 15 | https://sf.eater.com/2017/5/2/15523164/ryan-scott-steve-dustin-top-chef-finn-town | Ryan Scott out, Steve Dustin in at Finn Town. |
| 16 | https://sf.eater.com/2015/6/24/8839823/chef-shuffles-pican-the-keystone-fish-and-farm | George Morrone out at Fish & Farm; Zack Freitas in. |
| 17 | https://sf.eater.com/2018/8/22/17769932/healdburg-shed-chef-shuffle-perry-hoffman | Bryan Oliver elevated (internal promotion edge type). |

## Chronicle anchors

| # | Source | What it gives us |
|---|--------|------------------|
| 18 | https://www.sfchronicle.com/food/restaurants/article/bay-area-closings-2025-21246280.php | The closures list — seeds "closed venue" nodes to chase alumni from. |
| 19 | https://www.sfchronicle.com/projects/2026/top-100-best-restaurants-san-francisco-bay-area | Top 100 bios are lineage-dense (chef histories per venue). |
| 20 | https://www.sfchronicle.com/food/restaurants/article/fu-hui-hua-best-new-restaurant-21210401.php | Fù Huì Huá: father-son lineage (William Ge → Tao Ge). Family-transmission edge type. |

## Search recipes for tonight (run at the venue)

- `"<closed restaurant name>" chef where now sf` per closure from #18
- `site:sf.eater.com "chef shuffle"` — the tag had weekly "bonanza" roundups 2013–2016
- `site:sf.eater.com chef leaves <venue>` and `former <venue> chef opens`
- Chef-bio pages of current SF restaurants (About/Chef pages) for inbound edges
- Eater SF archives 2014–2016 are the goldmine era for roundups

## Edge-type legend (for the schema's `role` field variety)

- **founded** (Chen → Betelnut), **exec chef** (Ong @ Betelnut), **moved to** (Lanham Anomaly → Athanor), **elevated** (Oliver at Healdsburg SHED), **replaced** (Dustin in at Finn Town), **family** (Ge → Ge)
