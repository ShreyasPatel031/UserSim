# Product Hunt top-list prediction: backtest

5554 featured launches, 2026-03-01 to 2026-10-24. Each test month is predicted by a model trained only on earlier months (test months: 2026-04, 2026-05, 2026-06, 2026-07, 2026-08, 2026-09, 2026-10). No votes, comments or ranks of the launch itself are used as inputs.

Recall@k = share of PH's actual top k that we put in our top k. In brackets: what random picking gets. A list counts only when it has at least 2k launches (days with fewer than 20 featured launches are left out of day@10).

Data coverage (share of launches with each signal): site loaded 95%, llm scored 99%, hn story before launch 31%, domain age known 71%, github repo 0%, maker launched before 41%.

## Overall lists

| | day@3 | day@5 | day@10 | week@3 | week@5 | week@10 | month@3 | month@5 | month@10 |
|---|---|---|---|---|---|---|---|---|---|
| model (headline: no follower counts) | 0.60 (0.17) | 0.64 (0.24) | 0.69 (0.34) | 0.41 (0.02) | 0.52 (0.03) | 0.51 (0.07) | 0.17 (0.01) | 0.27 (0.01) | 0.28 (0.01) |
| model + today's follower counts (may leak) | 0.60 (0.17) | 0.66 (0.24) | 0.73 (0.34) | 0.39 (0.02) | 0.51 (0.03) | 0.54 (0.07) | 0.28 (0.01) | 0.40 (0.01) | 0.42 (0.01) |

95% confidence intervals (bootstrap over lists) and number of lists, headline model: day@3 0.57-0.63 (n=200); day@5 0.61-0.67 (n=177); day@10 0.67-0.72 (n=111); week@3 0.33-0.48 (n=28); week@5 0.46-0.58 (n=28); week@10 0.47-0.55 (n=28); month@3 0.06-0.28 (n=6); month@5 0.20-0.33 (n=6); month@10 0.20-0.37 (n=6).

Week and month results rest on few lists, so differences of a few points between rows below are noise.

Mean Spearman correlation with the daily order: 0.606

Per test month (each month's model learned only from earlier months; April and May are partly collected):

| month | day@3 | day@5 | day@10 | week@5 | week@10 |
|---|---|---|---|---|---|
| 2026-04 | 0.47 | 0.50 | 0.60 | 0.40 | 0.37 |
| 2026-05 | 0.56 | 0.61 | 0.71 | 0.55 | 0.55 |
| 2026-06 | 0.68 | 0.71 | 0.74 | 0.60 | 0.55 |
| 2026-07 | 0.68 | 0.68 | 0.74 | 0.47 | 0.57 |
| 2026-08 | 0.61 | 0.67 | 0.69 | 0.50 | 0.50 |
| 2026-09 | 0.58 | 0.67 | 0.71 | 0.60 | 0.53 |
| 2026-10 | 0.67 | 0.68 | 0.72 | 0.60 | 0.45 |

## Baselines (no model)

| | day@3 | day@5 | day@10 | week@3 | week@5 | week@10 | month@3 | month@5 | month@10 |
|---|---|---|---|---|---|---|---|---|---|
| followers today (hunter+makers; leaky) | 0.44 | 0.56 | 0.68 | 0.07 | 0.14 | 0.28 | 0.06 | 0.07 | 0.08 |
| llm p_top5 alone | 0.28 | 0.38 | 0.48 | 0.01 | 0.04 | 0.10 | 0.00 | 0.00 | 0.02 |
| look-alike earlier launches | 0.29 | 0.38 | 0.47 | 0.04 | 0.09 | 0.13 | 0.00 | 0.00 | 0.03 |

## Which sources predict: each source alone, and all sources minus one

Each source alone:

| | day@5 | day@10 | week@10 | month@10 |
|---|---|---|---|---|
| launch | 0.43 | 0.51 | 0.19 | 0.02 |
| people | 0.56 | 0.66 | 0.37 | 0.27 |
| history | 0.58 | 0.68 | 0.25 | 0.05 |
| site | 0.38 | 0.47 | 0.19 | 0.07 |
| llm | 0.40 | 0.50 | 0.12 | 0.02 |
| hn | 0.35 | 0.46 | 0.09 | 0.02 |
| domain | 0.34 | 0.42 | 0.12 | 0.00 |
| github | 0.24 | 0.35 | 0.05 | 0.05 |

All sources minus one (a drop below the full model = that source adds information):

| | day@5 | day@10 | week@10 | month@10 |
|---|---|---|---|---|
| (full model) | 0.64 | 0.69 | 0.51 | 0.28 |
| without launch | 0.63 | 0.68 | 0.53 | 0.33 |
| without people | 0.60 | 0.69 | 0.33 | 0.12 |
| without history | 0.58 | 0.68 | 0.42 | 0.23 |
| without site | 0.64 | 0.69 | 0.53 | 0.28 |
| without llm | 0.63 | 0.69 | 0.53 | 0.30 |
| without hn | 0.64 | 0.69 | 0.51 | 0.33 |
| without domain | 0.64 | 0.69 | 0.51 | 0.33 |
| without github | 0.63 | 0.69 | 0.52 | 0.33 |

## Which factors matter (mean |SHAP| on held-out launches)

Share of the model's attribution by source:

| source | share |
|---|---|
| history | 33% |
| launch | 23% |
| people | 21% |
| site | 10% |
| llm | 9% |
| hn | 3% |
| domain | 2% |
| github | 0% |

Top 20 features:

| feature | mean |SHAP| |
|---|---|
| hist_hunter_prior_top10_rate | 0.1427 |
| people_n_makers | 0.1306 |
| launch_n_featured_day | 0.0950 |
| hist_hunter_prior_hunts | 0.0484 |
| people_hunter_age_days | 0.0355 |
| hist_maker_prior_launches | 0.0322 |
| llm_p_top5 | 0.0268 |
| hist_maker_prior_top10_rate | 0.0249 |
| people_maker_age_max_days | 0.0240 |
| llm_broad_appeal | 0.0239 |
| launch_weekday | 0.0197 |
| domain_age_days | 0.0197 |
| site_w_ai | 0.0176 |
| launch_n_links | 0.0164 |
| hist_topic_top10_rate_mean | 0.0154 |
| site_words_log | 0.0138 |
| hist_lookalike_similarity | 0.0137 |
| launch_link_twitter | 0.0135 |
| hist_topic_top10_rate_max | 0.0130 |
| hist_lookalike_top3_rate | 0.0125 |

## How it changes by product type

Each source alone, ranking one type's launches against each other within each week (week recall@5; random in brackets):

| type | launch | people | history | site | llm | hn | domain | github |
|---|---|---|---|---|---|---|---|---|
| Developer (random 0.08) | 0.19 | 0.31 | 0.33 | 0.24 | 0.16 | 0.11 | 0.15 | 0.04 |
| AI (random 0.12) | 0.20 | 0.47 | 0.28 | 0.17 | 0.17 | 0.12 | 0.17 | 0.14 |
| Marketing & Sales | – | – | – | – | – | – | – | – |
| Other (random 0.29) | 0.40 | 0.60 | 0.67 | 0.27 | 0.47 | 0.67 | 0.33 | 0.40 |
| Productivity (random 0.22) | 0.34 | 0.37 | 0.37 | 0.34 | 0.29 | 0.29 | 0.34 | 0.26 |
| Consumer | – | – | – | – | – | – | – | – |
| Design | – | – | – | – | – | – | – | – |
| (all types) (random 0.03) | 0.10 | 0.34 | 0.09 | 0.09 | 0.06 | 0.06 | 0.06 | 0.03 |

Factors that go with more votes inside the same week (Spearman, launches de-meaned by week):

- **(all types)** (n=5554): hist_hunter_prior_top10_rate +0.43, people_self_hunted -0.43, people_hunter_age_days +0.40, people_n_makers +0.36, hist_hunter_prior_hunts +0.33, launch_n_featured_day -0.32, hist_maker_is_repeat +0.30, llm_maker_credibility +0.28
- **AI** (n=1573): people_hunter_age_days +0.45, people_self_hunted -0.44, hist_hunter_prior_hunts +0.43, people_n_makers +0.37, hist_hunter_prior_top10_rate +0.30, people_hunter_twitter +0.29, launch_n_links +0.29, llm_maker_credibility +0.27
- **Consumer** (n=189): people_self_hunted -0.32, hist_maker_is_repeat +0.30, hist_maker_prior_launches +0.28, launch_n_featured_day -0.26, launch_n_links +0.25, people_n_makers +0.23, people_hunter_age_days +0.21, hist_hunter_prior_top10_rate +0.17
- **Design** (n=228): llm_p_top5 +0.41, launch_n_featured_day -0.36, people_hunter_age_days +0.33, launch_n_links +0.29, llm_maker_credibility +0.28, llm_demo_wow +0.28, hist_hunter_prior_hunts +0.27, launch_link_twitter +0.27
- **Developer** (n=2302): people_self_hunted -0.47, people_hunter_age_days +0.45, hist_hunter_prior_hunts +0.42, people_n_makers +0.35, launch_n_featured_day -0.33, people_hunter_twitter +0.33, hist_hunter_prior_top10_rate +0.32, llm_maker_credibility +0.32
- **Marketing & Sales** (n=191): hist_hunter_prior_top10_rate +0.39, people_n_makers +0.34, people_hunter_age_days +0.31, people_self_hunted -0.30, hist_maker_is_repeat +0.28, launch_n_media +0.24, hist_hunter_prior_hunts +0.24, hist_maker_prior_launches +0.23
- **Other** (n=553): launch_n_featured_day -0.32, llm_broad_appeal +0.32, hist_hunter_prior_top10_rate +0.29, launch_hour +0.26, people_n_makers +0.24, site_is_subdomain -0.23, launch_n_media +0.23, llm_p_top5 +0.22
- **Productivity** (n=518): launch_n_featured_day -0.32, hist_hunter_prior_top10_rate +0.31, people_self_hunted -0.27, people_hunter_age_days +0.24, people_n_makers +0.22, people_hunter_twitter +0.20, hist_lookalike_top3_rate +0.18, hist_maker_is_repeat +0.18

SHAP share by source within each type (one shared model, so shares barely differ) (launches per type: {'Developer': 2006, 'AI': 1344, 'Other': 513, 'Productivity': 457, 'Design': 211, 'Consumer': 175, 'Marketing & Sales': 172}):

| type | history | launch | people | site | llm | hn | domain | github |
|---|---|---|---|---|---|---|---|---|
| AI | 34% | 21% | 22% | 9% | 9% | 3% | 2% | 0% |
| Consumer | 31% | 25% | 22% | 9% | 9% | 2% | 2% | 0% |
| Design | 30% | 24% | 22% | 10% | 9% | 3% | 2% | 0% |
| Developer | 33% | 23% | 21% | 10% | 8% | 3% | 2% | 0% |
| Marketing & Sales | 32% | 25% | 19% | 10% | 10% | 2% | 2% | 0% |
| Other | 30% | 24% | 21% | 10% | 10% | 3% | 2% | 0% |
| Productivity | 30% | 25% | 22% | 10% | 8% | 2% | 2% | 0% |

Top features per type:

- **Developer**: hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, hist_maker_prior_launches
- **AI**: hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, hist_maker_prior_launches
- **Other**: hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, llm_broad_appeal
- **Marketing & Sales**: hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, hist_maker_prior_launches
- **Design**: people_n_makers, hist_hunter_prior_top10_rate, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, hist_maker_prior_launches
- **Productivity**: people_n_makers, hist_hunter_prior_top10_rate, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, hist_maker_prior_launches
- **Consumer**: people_n_makers, hist_hunter_prior_top10_rate, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, hist_maker_prior_launches

## Topic lists (the model's score ranked inside each topic)

| | day@3 | day@5 | week@5 | week@10 | month@10 |
|---|---|---|---|---|---|
| Artificial Intelligence | 0.66 (0.26) | 0.69 (0.34) | 0.50 (0.07) | 0.56 (0.13) | 0.38 (0.03) |
| Productivity | 0.67 (0.33) | 0.64 (0.41) | 0.67 (0.10) | 0.70 (0.21) | 0.58 (0.05) |
| Developer Tools | 0.70 (0.35) | 0.66 (0.40) | 0.56 (0.10) | 0.66 (0.20) | 0.48 (0.05) |
| GitHub | 0.61 (0.38) | 0.56 (0.42) | 0.62 (0.18) | 0.67 (0.32) | 0.57 (0.10) |
| Open Source | 0.59 (0.38) | 0.65 (0.45) | 0.72 (0.24) | 0.70 (0.35) | 0.60 (0.14) |
| Mac | 0.50 (0.44) | 0.40 (0.50) | 0.35 (0.21) | 0.33 (0.32) | 0.58 (0.21) |
| SaaS | 0.72 (0.43) | – | 0.47 (0.22) | 0.73 (0.44) | 0.68 (0.21) |
| Marketing | 0.67 (0.50) | – | 0.73 (0.37) | – | 0.63 (0.23) |
| Design Tools | 0.67 (0.42) | – | 0.67 (0.40) | – | 0.63 (0.23) |
| API | – | – | – | – | 0.62 (0.33) |
| Menu Bar Apps | 0.67 (0.50) | – | 0.40 (0.26) | – | 0.58 (0.37) |
| Tech | 0.67 (0.50) | – | – | – | 0.62 (0.34) |
| Vercel Day | 0.73 (0.10) | 0.68 (0.17) | – | – | 0.70 (0.32) |
| iOS | 0.67 (0.43) | – | – | – | 0.73 (0.41) |
| Video | – | – | 0.80 (0.50) | – | 0.75 (0.38) |

## The lists on PH's homepage now

### yesterday (2026-10-24, 14 launches)

recall@3 1.00, recall@5 0.80, recall@10 0.70

| # | actual | predicted |
|---|---|---|
| 1 | zCAD AI | zCAD AI |
| 2 | myPip | myPip |
| 3 | 1Password for Agents | 1Password for Agents |
| 4 | AgentValley | LinkIntel |
| 5 | Canva Craft | Canva Craft |
| 6 | LinkIntel | sideOS.ai |
| 7 | Many Displays | Shedi |
| 8 | Penta | River Writer |
| 9 | Byter | Many Displays |
| 10 | Basedash Scheduled CSV Exports | AgentValley |

### last week (2026-10-12, 203 launches)

recall@3 0.67, recall@5 0.80, recall@10 0.50

| # | actual | predicted |
|---|---|---|
| 1 | Pancake | Pancake |
| 2 | Jockey by TwelveLabs | NitroStack |
| 3 | Inferock | Jockey by TwelveLabs |
| 4 | Articos MCP | Articos MCP |
| 5 | Talanoa | Talanoa |
| 6 | Harness by Autonomous | Confidence by Spotify  |
| 7 | OpenCode 2.0 | Agent Vault |
| 8 | Google EmbeddingGemma 2 | MentionBird |
| 9 | Inbox Zero | Ancher 2.0 |
| 10 | NitroStack | OpenMuse |

### last month (2026-09, 708 launches)

recall@3 0.33, recall@5 0.40, recall@10 0.40

| # | actual | predicted |
|---|---|---|
| 1 | Ami AI | CREEM 2.0 |
| 2 | tiun. | Clueso MCP |
| 3 | CREEM 2.0 | MCP Connectors by Databox |
| 4 | Clueso MCP | Hemory |
| 5 | Mastra Factory | Weave Router 2.0 |
| 6 | Jev | tiun. |
| 7 | Voiskey | Pexo |
| 8 | Switch | Ami AI |
| 9 | Naoma AI Demo Agent V2 | Scholé Learn by Building |
| 10 | Kilo Code for JetBrains | Humalike - AI NPC |

