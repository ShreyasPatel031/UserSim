# Product Hunt top-list predictor: backtest

Test months: 2026-09, 2026-10, each predicted by a model trained only on earlier launches. 1458 launches, 54 daily lists, 8 weekly lists. No vote, comment or rank field of the launch itself is used as an input.

## Recall@k (share of the real top k that the predicted top k contains), 95% CI over lists

| Method | Day @3 | Day @5 | Day @10 | Week @3 | Week @5 | Week @10 | Month @3 | Month @5 | Month @10 |
|---|---|---|---|---|---|---|---|---|---|
| Full model (all sources) | 58% (52%–64%) | 68% (63%–73%) | 77% (75%–80%) | 56% (39%–78%) | 53% (37%–67%) | 55% (47%–63%) | 33% (33%–33%) | 30% (20%–40%) | 35% (30%–40%) |
| Full model, ranking objective | 58% (52%–64%) | 67% (61%–72%) | 77% (74%–79%) | 50% (39%–61%) | 53% (43%–67%) | 57% (52%–63%) | 33% (33%–33%) | 40% (20%–60%) | 40% (40%–40%) |
| D. PH audience/metadata only | 55% (50%–60%) | 65% (60%–69%) | 77% (73%–80%) | 56% (44%–67%) | 57% (43%–70%) | 57% (47%–67%) | 50% (33%–67%) | 30% (20%–40%) | 35% (30%–40%) |
| C. LLM, pitch + homepage | 15% (10%–21%) | 27% (22%–33%) | 48% (42%–53%) | 0% (0%–0%) | 0% (0%–0%) | 2% (0%–5%) | 0% (0%–0%) | 0% (0%–0%) | 0% (0%–0%) |
| B. LLM, pitch only | 22% (17%–29%) | 35% (30%–40%) | 55% (50%–60%) | 0% (0%–0%) | 0% (0%–0%) | 7% (0%–17%) | 0% (0%–0%) | 0% (0%–0%) | 0% (0%–0%) |
| A. Random | 15% (10%–20%) | 23% (17%–29%) | 45% (39%–51%) | 11% (0%–22%) | 7% (0%–13%) | 7% (3%–10%) | 0% (0%–0%) | 0% (0%–0%) | 0% (0%–0%) |
| Full + maker followers (leaky) | 61% | 68% | 77% | 56% | 57% | 52% | 67% | 40% | 35% |

## Which sources predict (recall@5 on daily lists, and rank correlation within a day)

| Source | Alone: day@5 | Alone: Spearman | Full minus source: day@5 | Change vs full |
|---|---|---|---|---|
| PH audience & metadata (hunter, makers, media) | 65% | 0.66 | 56% | -12 pts |
| Hunter/maker track record on PH | 57% | 0.54 | 66% | -3 pts |
| Pitch text (name, tagline, description) | 39% | 0.30 | 67% | -1 pts |
| Homepage content | 24% | -0.10 | 68% | -0 pts |
| Domain (age, TLD, archive history) | 23% | nan | 68% | +0 pts |
| X/Twitter audience | 49% | 0.36 | 67% | -1 pts |
| Hacker News before launch | 23% | nan | 68% | +0 pts |
| Similar earlier PH launches | 33% | 0.13 | 67% | -1 pts |
| Topic priors | 39% | 0.23 | 67% | -1 pts |
| LLM judgement | 30% | 0.25 | 68% | -0 pts |

## Share of the model's decision by source, per product type

| Type | comp | dom | hist | hn | llm | ph | topic | txt | web | x |
|---|---|---|---|---|---|---|---|---|---|---|
| ai | 2% | 0% | 11% | 0% | 5% | 69% | 5% | 1% | 3% | 4% |
| consumer | 2% | 0% | 9% | 0% | 6% | 66% | 9% | 1% | 3% | 5% |
| design | 2% | 0% | 10% | 0% | 5% | 67% | 7% | 1% | 3% | 4% |
| dev | 2% | 0% | 9% | 0% | 5% | 68% | 7% | 1% | 3% | 4% |
| marketing | 2% | 0% | 11% | 0% | 5% | 64% | 10% | 1% | 2% | 5% |
| other | 2% | 0% | 9% | 0% | 6% | 68% | 7% | 1% | 2% | 5% |
| productivity | 2% | 0% | 7% | 0% | 5% | 67% | 9% | 1% | 3% | 5% |

## Top factors (mean |contribution| to predicted log votes)

- `ph_hunter_followers`: 0.238
- `ph_day_n_launches`: 0.075
- `ph_dayrank_ph_hunter_followers`: 0.056
- `ph_dayrank_ph_n_makers`: 0.054
- `llm_pitch`: 0.044
- `topic_prior_mean`: 0.034
- `hist_hunter_rel`: 0.032
- `ph_n_makers`: 0.028
- `web_dayrank_web_text_words`: 0.025
- `ph_hunter_age_d`: 0.023
- `ph_maker_min_age_d`: 0.021
- `ph_dayrank_ph_n_media`: 0.019
- `comp_nn_mean`: 0.015
- `ph_name_len`: 0.015
- `ph_dayrank_ph_hunter_age_d`: 0.015
- `x_dayrank_x_hunter_followers`: 0.013
- `hist_maker_top5`: 0.013
- `x_dayrank_x_maker_max_followers`: 0.013
- `txt_ridge`: 0.012
- `hist_dayrank_hist_hunter_rel`: 0.012

## Top 5 factors per product type

- **ai**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_n_makers`, `ph_dayrank_ph_hunter_followers`, `llm_pitch`
- **consumer**: `ph_hunter_followers`, `ph_day_n_launches`, `topic_prior_mean`, `llm_pitch`, `ph_dayrank_ph_hunter_followers`
- **design**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_hunter_followers`, `ph_dayrank_ph_n_makers`, `llm_pitch`
- **dev**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_hunter_followers`, `ph_dayrank_ph_n_makers`, `llm_pitch`
- **marketing**: `ph_hunter_followers`, `ph_day_n_launches`, `topic_prior_mean`, `ph_dayrank_ph_hunter_followers`, `ph_dayrank_ph_n_makers`
- **other**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_n_makers`, `ph_dayrank_ph_hunter_followers`, `llm_pitch`
- **productivity**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_hunter_followers`, `topic_prior_mean`, `llm_pitch`

## Topic lists (top k by votes within a topic), recall@5

| Topic | Day: model | Day: random | Week: model | Week: random | Month: model | Month: random |
|---|---|---|---|---|---|---|
| API | – | – | – | – | 50% | 20% |
| Android | 100% | 100% | – | – | 70% | 10% |
| Artificial Intelligence | 76% | 38% | 47% | 13% | 30% | 0% |
| Design Tools | 90% | 80% | 70% | 40% | 60% | 10% |
| Developer Tools | 82% | 56% | 48% | 12% | 40% | 0% |
| GitHub | 76% | 68% | 60% | 10% | 50% | 0% |
| Mac | 80% | 82% | 47% | 20% | 40% | 20% |
| Marketing | 100% | 95% | 80% | 70% | 50% | 50% |
| Menu Bar Apps | 80% | 80% | 60% | 20% | 60% | 20% |
| Open Source | 81% | 76% | 64% | 24% | 50% | 10% |
| OpenAI Day | 40% | 20% | – | – | 40% | 20% |
| Productivity | 78% | 61% | 70% | 7% | 40% | 0% |
| SaaS | 80% | 90% | 40% | 20% | 40% | 20% |
| Video | 100% | 100% | 80% | 40% | 60% | 30% |
| iOS | 100% | 100% | – | – | 40% | 10% |

## The three front-page lists (as of Oct 25), model trained only on earlier months

### Yesterday's Top Products (Oct 24): 14 launches; hits in top 3/5/10: 3/3, 3/5, 7/10

| # | Actual | Predicted |
|---|---|---|
| 1 | zCAD AI ✓ | zCAD AI (actual #1) |
| 2 | myPip ✓ | myPip (actual #2) |
| 3 | 1Password for Agents ✓ | 1Password for Agents (actual #3) |
| 4 | AgentValley | sideOS.ai (actual #11) |
| 5 | Canva Craft ✓ | LinkIntel (actual #6) |
| 6 | LinkIntel ✓ | Canva Craft (actual #5) |
| 7 | Many Displays ✓ | Many Displays (actual #7) |
| 8 | Penta | Shedi (actual #14) |
| 9 | Byter | River Writer (actual #12) |
| 10 | Basedash Scheduled CSV Exports ✓ | Basedash Scheduled CSV Exports (actual #10) |

### Last Week's Top Products (Oct 12–18): 203 launches; hits in top 3/5/10: 1/3, 3/5, 5/10

| # | Actual | Predicted |
|---|---|---|
| 1 | Pancake ✓ | Pancake (actual #1) |
| 2 | Jockey by TwelveLabs ✓ | NitroStack (actual #10) |
| 3 | Inferock | Articos MCP (actual #4) |
| 4 | Articos MCP ✓ | Jockey by TwelveLabs (actual #2) |
| 5 | Talanoa | guilds.run (actual #25) |
| 6 | Harness by Autonomous | Krea 3 (actual #134) |
| 7 | OpenCode 2.0 | Tiden (actual #19) |
| 8 | Google EmbeddingGemma 2 | MentionBird (actual #33) |
| 9 | Inbox Zero ✓ | Inbox Zero (actual #9) |
| 10 | NitroStack ✓ | AdAnt 2.0 (actual #27) |

### Last Month's Top Products (September): 708 launches; hits in top 3/5/10: 1/3, 1/5, 3/10

| # | Actual | Predicted |
|---|---|---|
| 1 | Ami AI ✓ | Hemory (actual #37) |
| 2 | tiun. | Ami AI (actual #1) |
| 3 | CREEM 2.0 ✓ | Monid (actual #16) |
| 4 | Clueso MCP ✓ | Pexo (actual #35) |
| 5 | Mastra Factory | Youkti  (actual #44) |
| 6 | Jev | CREEM 2.0 (actual #3) |
| 7 | Voiskey | GPT-6 Astra (actual #11) |
| 8 | Switch | Clueso MCP (actual #4) |
| 9 | Naoma AI Demo Agent V2 | RankControl (actual #231) |
| 10 | Kilo Code for JetBrains | Superset Mobile (actual #12) |

## Accuracy by product type

| Type | Launches | Real day-top-5 launches | Share the model had in its day top 5 | Rank correlation within type |
|---|---|---|---|---|

## Data coverage

- Homepage: Wayback snapshot from before launch 0%, live site 30%, none found 70%
- Products the LLM said it recognised (dropped): 0