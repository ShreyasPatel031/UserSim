# Product Hunt top-list predictor: backtest

Test months: 2026-10, each predicted by a model trained only on earlier launches. 750 launches, 24 daily lists, 4 weekly lists. No vote, comment or rank field of the launch itself is used as an input.

## Recall@k (share of the real top k that the predicted top k contains), 95% CI over lists

| Method | Day @3 | Day @5 | Day @10 | Week @3 | Week @5 | Week @10 | Month @3 | Month @5 | Month @10 |
|---|---|---|---|---|---|---|---|---|---|
| Full model (all sources) | 49% | 55% | 72% | 67% | 50% | 40% | 67% | 40% | 30% |
| Full model, ranking objective | 54% | 62% | 70% | 33% | 60% | 60% | 33% | 20% | 40% |
| D. PH audience/metadata only | 64% | 65% | 74% | 67% | 60% | 50% | 33% | 20% | 30% |
| C. LLM, pitch + homepage | 15% | 22% | 36% | 0% | 0% | 10% | 0% | 0% | 10% |
| B. LLM, pitch only | 24% | 32% | 50% | 0% | 0% | 20% | 0% | 0% | 0% |
| A. Random | 10% | 12% | 35% | 0% | 0% | 5% | 0% | 0% | 0% |
| Full + maker followers (leaky) | 47% | 57% | 73% | 33% | 50% | 45% | 67% | 40% | 30% |

## Which sources predict (recall@5 on daily lists, and rank correlation within a day)

| Source | Alone: day@5 | Alone: Spearman | Full minus source: day@5 | Change vs full |
|---|---|---|---|---|
| PH audience & metadata (hunter, makers, media) | 65% | 0.65 | 47% | -8 pts |
| Hunter/maker track record on PH | 49% | 0.57 | 62% | +7 pts |
| Pitch text (name, tagline, description) | 30% | 0.26 | 56% | +1 pts |
| Homepage content | 23% | -0.14 | 58% | +3 pts |
| Domain (age, TLD, archive history) | 18% | nan | 55% | +0 pts |
| X/Twitter audience | 51% | 0.40 | 59% | +4 pts |
| Hacker News before launch | 18% | nan | 55% | +0 pts |
| Similar earlier PH launches | 21% | 0.06 | 62% | +7 pts |
| Topic priors | 29% | 0.19 | 56% | +1 pts |
| LLM judgement | 27% | 0.22 | 55% | -0 pts |

## Share of the model's decision by source, per product type

| Type | comp | dom | hist | hn | llm | ph | topic | txt | web | x |
|---|---|---|---|---|---|---|---|---|---|---|
| ai | 4% | 0% | 14% | 0% | 2% | 67% | 5% | 3% | 2% | 4% |
| consumer | 3% | 0% | 12% | 0% | 2% | 68% | 7% | 2% | 3% | 4% |
| design | 2% | 0% | 12% | 0% | 2% | 68% | 6% | 3% | 2% | 4% |
| dev | 3% | 0% | 12% | 0% | 2% | 68% | 6% | 3% | 3% | 4% |
| marketing | 5% | 0% | 12% | 0% | 2% | 63% | 10% | 2% | 2% | 4% |
| other | 3% | 0% | 13% | 0% | 2% | 66% | 7% | 3% | 2% | 4% |
| productivity | 4% | 0% | 10% | 0% | 1% | 67% | 7% | 3% | 3% | 4% |

## Top factors (mean |contribution| to predicted log votes)

- `ph_hunter_followers`: 0.244
- `ph_day_n_launches`: 0.065
- `ph_dayrank_ph_n_makers`: 0.051
- `ph_n_makers`: 0.033
- `hist_hunter_top5`: 0.033
- `ph_dayrank_ph_hunter_followers`: 0.026
- `ph_maker_min_age_d`: 0.026
- `txt_ridge`: 0.024
- `topic_prior_mean`: 0.024
- `web_dayrank_web_text_words`: 0.020
- `comp_nn_mean`: 0.020
- `hist_hunter_rel`: 0.018
- `ph_dayrank_ph_n_media`: 0.017
- `topic_prior_max`: 0.016
- `llm_pitch`: 0.016
- `ph_dayrank_ph_hunter_age_d`: 0.015
- `ph_tagline_len`: 0.014
- `hist_maker_top5`: 0.014
- `ph_weekday`: 0.014
- `ph_maker_max_age_d`: 0.014

## Top 5 factors per product type

- **ai**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_n_makers`, `hist_hunter_top5`, `ph_n_makers`
- **consumer**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_n_makers`, `ph_n_makers`, `hist_hunter_top5`
- **design**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_n_makers`, `ph_n_makers`, `hist_hunter_top5`
- **dev**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_n_makers`, `ph_n_makers`, `hist_hunter_top5`
- **marketing**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_n_makers`, `topic_prior_max`, `topic_prior_mean`
- **other**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_n_makers`, `hist_hunter_top5`, `ph_n_makers`
- **productivity**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_n_makers`, `topic_prior_max`, `ph_n_makers`

## Topic lists (top k by votes within a topic), recall@5

| Topic | Day: model | Day: random | Week: model | Week: random | Month: model | Month: random |
|---|---|---|---|---|---|---|
| Android | 100% | 100% | – | – | 60% | 20% |
| Artificial Intelligence | 72% | 27% | 50% | 0% | 40% | 0% |
| Design Tools | – | – | 40% | 60% | 40% | 20% |
| Developer Tools | 78% | 50% | 30% | 0% | 20% | 0% |
| GitHub | 76% | 64% | 70% | 20% | 40% | 0% |
| Google Cloud Run | 80% | 20% | – | – | 80% | 20% |
| Mac | 76% | 72% | 40% | 40% | 60% | 20% |
| Marketing | 100% | 100% | 60% | 40% | 40% | 40% |
| Menu Bar Apps | 100% | 80% | – | – | 60% | 20% |
| Open Source | 75% | 68% | 60% | 20% | 60% | 20% |
| Privacy | 100% | 100% | – | – | 60% | 0% |
| Productivity | 76% | 51% | 50% | 0% | 40% | 0% |
| SaaS | 100% | 100% | – | – | 20% | 20% |
| Video | – | – | 80% | 60% | 40% | 20% |
| iOS | – | – | – | – | 40% | 0% |

## The three front-page lists (as of Oct 25), model trained only on earlier months

### Yesterday's Top Products (Oct 24): 14 launches; hits in top 3/5/10: 2/3, 4/5, 6/10

| # | Actual | Predicted |
|---|---|---|
| 1 | zCAD AI ✓ | zCAD AI (actual #1) |
| 2 | myPip ✓ | myPip (actual #2) |
| 3 | 1Password for Agents ✓ | Canva Craft (actual #5) |
| 4 | AgentValley | LinkIntel (actual #6) |
| 5 | Canva Craft ✓ | 1Password for Agents (actual #3) |
| 6 | LinkIntel ✓ | sideOS.ai (actual #11) |
| 7 | Many Displays ✓ | Many Displays (actual #7) |
| 8 | Penta | River Writer (actual #12) |
| 9 | Byter | Shedi (actual #14) |
| 10 | Basedash Scheduled CSV Exports | How It Went (actual #13) |

### Last Week's Top Products (Oct 12–18): 203 launches; hits in top 3/5/10: 2/3, 3/5, 4/10

| # | Actual | Predicted |
|---|---|---|
| 1 | Pancake ✓ | Pancake (actual #1) |
| 2 | Jockey by TwelveLabs ✓ | Jockey by TwelveLabs (actual #2) |
| 3 | Inferock | Articos MCP (actual #4) |
| 4 | Articos MCP ✓ | NitroStack (actual #10) |
| 5 | Talanoa | AdAnt 2.0 (actual #27) |
| 6 | Harness by Autonomous | Fish Audio Drama 3 (actual #47) |
| 7 | OpenCode 2.0 | PostNitro for Agents (actual #41) |
| 8 | Google EmbeddingGemma 2 | MentionBird (actual #33) |
| 9 | Inbox Zero | Tiden (actual #19) |
| 10 | NitroStack ✓ | Pomerado (actual #30) |

## Data coverage

- Homepage: Wayback snapshot from before launch 0%, live site 48%, none found 52%
- Products the LLM said it recognised (dropped): 0