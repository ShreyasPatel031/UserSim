# Product Hunt top-list predictor: backtest

Test months: 2026-03, 2026-04, 2026-05, 2026-06, 2026-07, 2026-08, 2026-09, 2026-10, each predicted by a model trained only on earlier launches. 5758 launches, 238 daily lists, 35 weekly lists. No vote, comment or rank field of the launch itself is used as an input.

## Key findings

1. **Daily list (Yesterday's Top Products): the model finds 59% of the real top 3, 68% of the top 5 and 78% of the top 10** (random: 20% / 32% / 48%). Accuracy rises as history accumulates: the July–October test months, with 6+ months to learn from, score higher on every list (table below).
2. **Weekly list: 55% / 54% / 52%** at top 3/5/10 with the weekly-list model (random 8% at top 10). **Monthly list: 25% / 38% / 40%** with the monthly-list model (only 8 monthly lists, so wide ranges). Weekly and monthly lists are harder because they compare launches across days: even a perfect within-day order gets only about half of a week's top 3, so these lists depend on predicting how big a day's winner gets.
3. **Who posts the launch matters most.** Product Hunt audience and metadata alone find 67% of the daily top 5; the hunter's and makers' track record alone 63%; X audience 53%; pitch text 45%; LLM judgements 43%; homepage 38%; Hacker News and domain age are near random (32%). Removing the PH audience source costs the most; removing any other source changes the full model by a point or less, so they carry little that the audience features do not already have.
4. **Reading the product barely helps.** An LLM ranking each day's launches from the pitch finds 42% of the top 5, and with the homepage 39%, against 32% random. In the plan's terms: D is best and B/C are only slightly above chance, so Product Hunt votes mostly measure distribution (the hunter's audience and record), not the product. A product-quality simulator should not be judged on raw PH votes without controlling for who posted the launch.
5. **Strongest single factors** (daily top-5 rate, high vs low): hunter's PH followers (top third 45% vs bottom third 1%); hunter's past top-5 rate (63% vs 8%); hunter account age (37% vs 7%); number of makers (46% vs 12%); LLM pitch score (37% vs 10%); weekend launch (45% vs 18%, fewer competitors). **Self-hunted launches finish top 5 9% of the time, others 34%.**
6. **Across product types** the hunter's audience dominates everywhere, but least in marketing and 'other' launches. There the pitch (LLM score), the makers' own record and gallery quality count for more; in productivity the hunter's past record counts most after audience; in consumer apps, hunter account age. The model is most accurate on AI launches (74% of their daily top-5 finishes caught) and least on productivity (47%).
7. **Leakage checks.** Maker follower counts are today's values (makers gain followers after a top launch), so they are left out; adding them back changes little. The LLM (training data older than every launch) recognised no product.

## Recall@k (share of the real top k that the predicted top k contains), 95% CI over lists

| Method | Day @3 | Day @5 | Day @10 | Week @3 | Week @5 | Week @10 | Month @3 | Month @5 | Month @10 |
|---|---|---|---|---|---|---|---|---|---|
| Full model (all sources) | 59% (56%–62%) | 68% (66%–71%) | 78% (76%–79%) | 41% (31%–51%) | 50% (44%–55%) | 55% (51%–59%) | 12% (0%–29%) | 18% (8%–28%) | 28% (21%–34%) |
| Weekly-list model | 55% (52%–58%) | 64% (61%–66%) | 75% (73%–77%) | 55% (47%–62%) | 54% (49%–59%) | 52% (48%–58%) | 25% (12%–42%) | 35% (28%–43%) | 41% (31%–52%) |
| Monthly-list model | 54% (51%–57%) | 62% (59%–65%) | 72% (70%–74%) | 49% (40%–59%) | 52% (46%–58%) | 51% (46%–56%) | 25% (17%–33%) | 38% (23%–52%) | 40% (31%–49%) |
| Full model, blend of both objectives | 60% (57%–63%) | 69% (66%–71%) | 77% (75%–79%) | 49% (40%–59%) | 54% (49%–58%) | 56% (53%–60%) | 25% (8%–46%) | 25% (15%–35%) | 38% (29%–46%) |
| Full model, ranking objective | 58% (55%–61%) | 68% (65%–70%) | 76% (74%–78%) | 51% (41%–61%) | 57% (53%–61%) | 55% (51%–58%) | 21% (4%–38%) | 22% (10%–38%) | 36% (28%–45%) |
| D. PH audience/metadata only | 57% (54%–60%) | 67% (64%–70%) | 76% (74%–78%) | 42% (32%–53%) | 53% (48%–58%) | 55% (52%–60%) | 21% (4%–38%) | 23% (12%–33%) | 30% (22%–39%) |
| C. LLM, pitch + homepage | 24% (21%–27%) | 39% (36%–43%) | 56% (53%–59%) | 2% (0%–5%) | 4% (1%–8%) | 9% (6%–12%) | 0% (0%–0%) | 0% (0%–0%) | 1% (0%–4%) |
| B. LLM, pitch only | 25% (22%–28%) | 42% (38%–45%) | 59% (56%–62%) | 1% (0%–3%) | 5% (1%–9%) | 11% (7%–14%) | 0% (0%–0%) | 0% (0%–0%) | 1% (0%–4%) |
| A. Random | 20% (17%–23%) | 32% (29%–36%) | 48% (44%–51%) | 2% (0%–5%) | 2% (1%–5%) | 8% (5%–11%) | 0% (0%–0%) | 0% (0%–0%) | 0% (0%–0%) |
| Full + maker followers (leaky) | 58% | 69% | 78% | 44% | 52% | 57% | 21% | 30% | 34% |

## Accuracy grows with training history

Same backtest, split by test months: early months had 2–5 months of history to learn from, later ones 6–9.

| Test months | List | Model | Top 3 | Top 5 | Top 10 |
|---|---|---|---|---|---|
| Mar–Jun | day | Full model | 54% | 66% | 75% |
| Mar–Jun | week | Weekly-list model | 55% | 51% | 48% |
| Mar–Jun | mon | Monthly-list model | 25% | 35% | 35% |
| Jul–Oct | day | Full model | 64% | 70% | 81% |
| Jul–Oct | week | Weekly-list model | 56% | 56% | 56% |
| Jul–Oct | mon | Monthly-list model | 25% | 40% | 45% |

## Which sources predict (recall@5 on daily lists, and rank correlation within a day)

| Source | Alone: day@5 | Alone: Spearman | Full minus source: day@5 | Change vs full |
|---|---|---|---|---|
| PH audience & metadata (hunter, makers, media) | 67% | 0.66 | 65% | -3 pts |
| Hunter/maker track record on PH | 63% | 0.56 | 67% | -1 pts |
| Pitch text (name, tagline, description) | 45% | 0.33 | 69% | +1 pts |
| Homepage content | 38% | 0.13 | 68% | +0 pts |
| Domain (age, TLD, archive history) | 32% | 0.06 | 68% | +0 pts |
| X/Twitter audience | 53% | 0.35 | 68% | +0 pts |
| Hacker News before launch | 33% | 0.02 | 68% | +0 pts |
| Similar earlier PH launches | 40% | 0.21 | 69% | +1 pts |
| Topic priors | 42% | 0.24 | 68% | +0 pts |
| LLM judgement | 43% | 0.31 | 68% | -0 pts |

## Share of the model's decision by source, per product type

| Type | comp | dom | hist | hn | llm | ph | topic | txt | web | x |
|---|---|---|---|---|---|---|---|---|---|---|
| ai | 2% | 2% | 13% | 0% | 6% | 61% | 4% | 3% | 4% | 4% |
| consumer | 1% | 2% | 11% | 0% | 8% | 64% | 4% | 2% | 4% | 4% |
| design | 2% | 2% | 11% | 0% | 7% | 63% | 4% | 3% | 4% | 4% |
| dev | 2% | 2% | 12% | 1% | 6% | 63% | 4% | 2% | 4% | 4% |
| marketing | 2% | 2% | 12% | 0% | 5% | 58% | 8% | 3% | 5% | 4% |
| other | 2% | 2% | 11% | 0% | 9% | 63% | 4% | 2% | 4% | 3% |
| productivity | 2% | 2% | 11% | 1% | 6% | 64% | 4% | 2% | 4% | 4% |

## Top factors (mean |contribution| to predicted log votes)

- `ph_hunter_followers`: 0.144
- `ph_day_n_launches`: 0.085
- `ph_dayrank_ph_hunter_followers`: 0.080
- `ph_dayrank_ph_n_makers`: 0.051
- `ph_n_makers`: 0.050
- `hist_hunter_rel`: 0.043
- `llm_pitch`: 0.037
- `ph_maker_min_age_d`: 0.028
- `hist_hunter_top5`: 0.027
- `ph_maker_max_age_d`: 0.027
- `txt_ridge`: 0.026
- `topic_prior_mean`: 0.022
- `llm_site`: 0.022
- `ph_month`: 0.021
- `ph_hunter_age_d`: 0.019
- `ph_name_len`: 0.015
- `x_dayrank_x_hunter_followers`: 0.014
- `hist_dayrank_hist_hunter_rel`: 0.012
- `ph_weekday`: 0.011
- `ph_tagline_len`: 0.010

## Top 5 factors per product type

- **ai**: `ph_hunter_followers`, `ph_dayrank_ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_n_makers`, `ph_n_makers`
- **consumer**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_hunter_followers`, `ph_n_makers`, `ph_dayrank_ph_n_makers`
- **design**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_hunter_followers`, `ph_dayrank_ph_n_makers`, `ph_n_makers`
- **dev**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_hunter_followers`, `ph_n_makers`, `ph_dayrank_ph_n_makers`
- **marketing**: `ph_hunter_followers`, `ph_dayrank_ph_hunter_followers`, `ph_day_n_launches`, `topic_prior_mean`, `ph_dayrank_ph_n_makers`
- **other**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_hunter_followers`, `ph_dayrank_ph_n_makers`, `llm_pitch`
- **productivity**: `ph_hunter_followers`, `ph_day_n_launches`, `ph_dayrank_ph_hunter_followers`, `ph_n_makers`, `ph_dayrank_ph_n_makers`

## Topic lists (top k by votes within a topic), recall@5

| Topic | Day: model | Day: random | Week: model | Week: random | Month: model | Month: random |
|---|---|---|---|---|---|---|
| API | 100% | 100% | – | – | 55% | 15% |
| Artificial Intelligence | 76% | 45% | 51% | 5% | 28% | 0% |
| Design Tools | 90% | 90% | 80% | 45% | 60% | 20% |
| Developer Tools | 83% | 63% | 52% | 11% | 35% | 0% |
| GitHub | 86% | 77% | 64% | 23% | 48% | 2% |
| Mac | 85% | 82% | 45% | 15% | 55% | 5% |
| Marketing | 98% | 96% | 73% | 53% | 57% | 10% |
| Menu Bar Apps | 100% | 90% | 40% | 20% | 62% | 20% |
| Open Source | 87% | 77% | 71% | 29% | 57% | 5% |
| Productivity | 81% | 62% | 66% | 11% | 30% | 8% |
| SaaS | 94% | 90% | 53% | 20% | 55% | 10% |
| Tech | 93% | 93% | – | – | 60% | 20% |
| Vercel Day | 60% | 16% | – | – | 60% | 20% |
| Video | 100% | 100% | 80% | 60% | 73% | 38% |
| iOS | 90% | 90% | – | – | 60% | 25% |

## The three front-page lists (as of Oct 25), model trained only on earlier months

### Yesterday's Top Products (Oct 24), full model: 14 launches; hits in top 3/5/10: 2/3, 4/5, 7/10

| # | Actual | Predicted |
|---|---|---|
| 1 | zCAD AI ✓ | myPip (actual #2) |
| 2 | myPip ✓ | zCAD AI (actual #1) |
| 3 | 1Password for Agents ✓ | LinkIntel (actual #6) |
| 4 | AgentValley ✓ | Canva Craft (actual #5) |
| 5 | Canva Craft ✓ | 1Password for Agents (actual #3) |
| 6 | LinkIntel ✓ | sideOS.ai (actual #11) |
| 7 | Many Displays | AgentValley (actual #4) |
| 8 | Penta | Shedi (actual #14) |
| 9 | Byter | River Writer (actual #12) |
| 10 | Basedash Scheduled CSV Exports ✓ | Basedash Scheduled CSV Exports (actual #10) |

### Last Week's Top Products (Oct 12–18), weekly-list model: 203 launches; hits in top 3/5/10: 1/3, 4/5, 5/10

| # | Actual | Predicted |
|---|---|---|
| 1 | Pancake ✓ | Pancake (actual #1) |
| 2 | Jockey by TwelveLabs ✓ | Articos MCP (actual #4) |
| 3 | Inferock | Agent Vault (actual #177) |
| 4 | Articos MCP ✓ | Jockey by TwelveLabs (actual #2) |
| 5 | Talanoa ✓ | Talanoa (actual #5) |
| 6 | Harness by Autonomous | NitroStack (actual #10) |
| 7 | OpenCode 2.0 | AdAnt 2.0 (actual #27) |
| 8 | Google EmbeddingGemma 2 | Tiden (actual #19) |
| 9 | Inbox Zero | SignWith (actual #17) |
| 10 | NitroStack ✓ | Kai (actual #21) |

### Last Month's Top Products (September), monthly-list model: 708 launches; hits in top 3/5/10: 1/3, 3/5, 5/10

| # | Actual | Predicted |
|---|---|---|
| 1 | Ami AI | Pexo (actual #35) |
| 2 | tiun. | CREEM 2.0 (actual #3) |
| 3 | CREEM 2.0 ✓ | Mastra Factory (actual #5) |
| 4 | Clueso MCP ✓ | Clueso MCP (actual #4) |
| 5 | Mastra Factory ✓ | iFixAi (actual #30) |
| 6 | Jev | Switch (actual #8) |
| 7 | Voiskey | Kilo Code for JetBrains (actual #10) |
| 8 | Switch ✓ | Superset Mobile (actual #12) |
| 9 | Naoma AI Demo Agent V2 | PR Lens by Coldtea.ai (actual #49) |
| 10 | Kilo Code for JetBrains ✓ | Weave Router 2.0 (actual #50) |

## Accuracy by product type

| Type | Launches | Real day-top-5 launches | Share the model had in its day top 5 | Rank correlation within type |
|---|---|---|---|---|
| ai | 2910 | 792 | 74% | 0.69 |
| dev | 956 | 170 | 54% | 0.60 |
| other | 765 | 59 | 58% | 0.55 |
| productivity | 595 | 72 | 47% | 0.50 |
| consumer | 188 | 29 | 69% | 0.61 |
| design | 173 | 25 | 76% | 0.40 |
| marketing | 171 | 43 | 67% | 0.50 |

## Forward test: Forecast for 2026-10-25 (made before results; 13 featured launches at fetch time)


| Predicted rank | Product | Tagline | Hunter PH followers |
|---|---|---|---|
| 1 | Moli by Lexmount | The fastest headless browser for agents and harnesses | 146076 |
| 2 | AgentGrid.io | Shared workspace for humans and agents | 241 |
| 3 | Llama Windows | One local AI server for all your Windows apps | 10952 |
| 4 | git-flow-next | Your favorite Git workflow. Reimagined. | 104145 |
| 5 | Openstatus Incident Management | Incident management for small teams | 104145 |
| 6 | How It Spread | See how anything went viral, from the first post | 84 |
| 7 | Papermark Data Rooms | Secure data rooms your AI agents can run. Live in < 60 sec. | 693 |
| 8 | Badgey | Your iPhone becomes a name badge that faces the room | 61 |
| 9 | pawl | a tiny mac focus timer you start by pulling a paw | 29 |
| 10 | MRRaudit | Understand why your MRR differs and get a number you trust | 23 |
| 11 | Clips by Plastic | Lyric video ads for every part of your song, on the beat | 9 |
| 12 | Specsight | Product observability for teams shipping fast with AI | 5 |
| 13 | Yourcast 2.0 | AI summaries with tap-to-jump timestamps, right in Telegram | 6 |

## Forward test: Forecast: Last Week's Top Products for 2026-W43 (trained on launches before 2026-10-19; 171 launches, 13 of them today with results not in)


| Predicted | Product | Day | Hunter PH followers | Real weekly rank so far |
|---|---|---|---|---|
| 1 | /dev/null | 2026-10-20 | 2687 | 1 |
| 2 | UseIt Studio | 2026-10-21 | 10950 | 7 |
| 3 | Needle | 2026-10-21 | 22805 | 10 |
| 4 | DeepCell | 2026-10-22 | 4674 | 4 |
| 5 | Fastlane 2.0 | 2026-10-22 | 22805 | 26 |
| 6 | Product Hunt Visual Launch Editor | 2026-10-23 | 4509 | 2 |
| 7 | CutBay | 2026-10-22 | 29014 | 34 |
| 8 | Beam.win | 2026-10-19 | 49842 | 3 |
| 9 | Doneas | 2026-10-22 | 685 | 13 |
| 10 | zCAD AI | 2026-10-24 | 107 | 11 |
| 11 | Hoistbay | 2026-10-20 | 22805 | 22 |
| 12 | Exa 3.0 | 2026-10-20 | 22805 | 24 |
| 13 | Resend Inboxes | 2026-10-22 | 104117 | 45 |
| 14 | MOVO AI | 2026-10-23 | 10950 | 9 |
| 15 | Moli by Lexmount | 2026-10-25 | 146076 | – |

Against the ranks so far (Oct 19–24 final, Oct 25 still open): top 3/5/10 hits 1/3, 2/5, 6/10.

## Launch-day homepage (Wayback snapshot) vs today's live site

September–October launches with a Wayback capture from before launch day: 186 launches over 31 days. Median word overlap between the two versions: 54%. A homepage-only model, cross-validated by day, predicting each launch's votes relative to its day (rank correlation within a day):

| Homepage version | Page structure features | Page words |
|---|---|---|
| snapshot | 0.21 | 0.10 |
| live | 0.23 | 0.12 |

## Data coverage

- Homepage: Wayback snapshot from before launch 0%, live site 63%, none found 37%
- Products the LLM said it recognised (dropped): 0