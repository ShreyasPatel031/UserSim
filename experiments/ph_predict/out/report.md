# Product Hunt top-list prediction: backtest

7696 featured launches, 2025-10-01 to 2026-10-24. Each test month is predicted by a model trained only on earlier months (test months: 2026-04, 2026-05, 2026-06, 2026-07, 2026-08, 2026-09, 2026-10). No votes, comments or ranks of the launch itself are used as inputs.

Recall@k = share of PH's actual top k that we put in our top k. In brackets: what random picking gets. A list counts only when it has at least 2k launches (days with fewer than 20 featured launches are left out of day@10).

Data coverage (share of launches with each signal): site loaded 94%, llm scored 100%, hn story before launch 32%, domain age known 71%, github repo 0%, maker launched before 44%.

## Overall lists

| | day@3 | day@5 | day@10 | week@3 | week@5 | week@10 | month@3 | month@5 | month@10 |
|---|---|---|---|---|---|---|---|---|---|
| model (headline: no follower counts) | 0.60 (0.17) | 0.66 (0.24) | 0.70 (0.34) | 0.42 (0.02) | 0.54 (0.03) | 0.54 (0.07) | 0.11 (0.01) | 0.20 (0.01) | 0.33 (0.01) |
| model + today's follower counts (may leak) | 0.61 (0.17) | 0.66 (0.24) | 0.73 (0.34) | 0.48 (0.02) | 0.54 (0.03) | 0.56 (0.07) | 0.17 (0.01) | 0.27 (0.01) | 0.40 (0.01) |

95% confidence intervals (bootstrap over lists) and number of lists, headline model: day@3 0.57-0.63 (n=200); day@5 0.63-0.68 (n=177); day@10 0.68-0.72 (n=111); week@3 0.33-0.51 (n=28); week@5 0.49-0.61 (n=28); week@10 0.50-0.58 (n=28); month@3 0.00-0.22 (n=6); month@5 0.10-0.30 (n=6); month@10 0.23-0.45 (n=6).

Week and month results rest on few lists, so differences of a few points between rows below are noise.

Mean Spearman correlation with the daily order: 0.636

Per test month (each month's model learned only from earlier months; April and May are partly collected):

| month | day@3 | day@5 | day@10 | week@5 | week@10 |
|---|---|---|---|---|---|
| 2026-04 | 0.49 | 0.55 | 0.62 | 0.33 | 0.47 |
| 2026-05 | 0.60 | 0.62 | 0.68 | 0.55 | 0.57 |
| 2026-06 | 0.63 | 0.74 | 0.74 | 0.60 | 0.47 |
| 2026-07 | 0.64 | 0.67 | 0.73 | 0.53 | 0.57 |
| 2026-08 | 0.61 | 0.68 | 0.69 | 0.50 | 0.57 |
| 2026-09 | 0.61 | 0.67 | 0.72 | 0.60 | 0.60 |
| 2026-10 | 0.61 | 0.68 | 0.75 | 0.60 | 0.40 |

## Baselines (no model)

| | day@3 | day@5 | day@10 | week@3 | week@5 | week@10 | month@3 | month@5 | month@10 |
|---|---|---|---|---|---|---|---|---|---|
| followers today (hunter+makers; leaky) | 0.44 | 0.56 | 0.68 | 0.07 | 0.14 | 0.28 | 0.06 | 0.07 | 0.08 |
| llm p_top5 alone | 0.26 | 0.38 | 0.47 | 0.04 | 0.05 | 0.09 | 0.00 | 0.00 | 0.02 |
| look-alike earlier launches | 0.28 | 0.35 | 0.43 | 0.05 | 0.06 | 0.14 | 0.06 | 0.03 | 0.07 |

## Which sources predict: each source alone, and all sources minus one

Each source alone:

| | day@5 | day@10 | week@10 | month@10 |
|---|---|---|---|---|
| launch | 0.43 | 0.53 | 0.19 | 0.03 |
| people | 0.54 | 0.65 | 0.39 | 0.30 |
| history | 0.58 | 0.68 | 0.30 | 0.10 |
| site | 0.39 | 0.47 | 0.19 | 0.03 |
| llm | 0.38 | 0.49 | 0.12 | 0.03 |
| hn | 0.36 | 0.45 | 0.10 | 0.00 |
| domain | 0.33 | 0.46 | 0.14 | 0.02 |
| github | 0.23 | 0.32 | 0.08 | 0.02 |

All sources minus one (a drop below the full model = that source adds information):

| | day@5 | day@10 | week@10 | month@10 |
|---|---|---|---|---|
| (full model) | 0.66 | 0.70 | 0.54 | 0.33 |
| without launch | 0.64 | 0.69 | 0.55 | 0.32 |
| without people | 0.61 | 0.70 | 0.39 | 0.12 |
| without history | 0.59 | 0.69 | 0.41 | 0.27 |
| without site | 0.66 | 0.70 | 0.56 | 0.30 |
| without llm | 0.65 | 0.71 | 0.55 | 0.32 |
| without hn | 0.66 | 0.70 | 0.55 | 0.32 |
| without domain | 0.65 | 0.70 | 0.54 | 0.30 |
| without github | 0.66 | 0.71 | 0.54 | 0.35 |

## Which factors matter (mean |SHAP| on held-out launches)

Share of the model's attribution by source:

| source | share |
|---|---|
| history | 34% |
| people | 24% |
| launch | 23% |
| site | 8% |
| llm | 7% |
| hn | 3% |
| domain | 1% |
| github | 0% |

Top 20 features:

| feature | mean |SHAP| |
|---|---|
| people_n_makers | 0.1489 |
| hist_hunter_prior_top10_rate | 0.1424 |
| launch_n_featured_day | 0.1278 |
| hist_maker_prior_launches | 0.0422 |
| hist_hunter_prior_hunts | 0.0398 |
| hist_maker_prior_top10_rate | 0.0362 |
| people_hunter_age_days | 0.0350 |
| llm_broad_appeal | 0.0308 |
| people_maker_age_max_days | 0.0237 |
| hist_topic_top10_rate_mean | 0.0206 |
| hist_lookalike_similarity | 0.0196 |
| llm_p_top5 | 0.0183 |
| launch_weekday | 0.0157 |
| site_w_ai | 0.0147 |
| domain_age_days | 0.0131 |
| hist_maker_prior_best_rank | 0.0121 |
| site_words_log | 0.0120 |
| hn_stories | 0.0116 |
| people_maker_twitter | 0.0114 |
| people_self_hunted | 0.0108 |

## How it changes by product type

Each source alone, ranking one type's launches against each other within each week (week recall@5; random in brackets):

| type | launch | people | history | site | llm | hn | domain | github |
|---|---|---|---|---|---|---|---|---|
| Developer (random 0.08) | 0.21 | 0.34 | 0.33 | 0.16 | 0.16 | 0.14 | 0.16 | 0.07 |
| AI (random 0.12) | 0.23 | 0.47 | 0.30 | 0.17 | 0.17 | 0.12 | 0.15 | 0.09 |
| Other (random 0.29) | 0.33 | 0.53 | 0.60 | 0.40 | 0.53 | 0.47 | 0.27 | 0.33 |
| Productivity (random 0.22) | 0.43 | 0.31 | 0.31 | 0.31 | 0.23 | 0.31 | 0.37 | 0.29 |
| Design | – | – | – | – | – | – | – | – |
| Consumer | – | – | – | – | – | – | – | – |
| Marketing & Sales | – | – | – | – | – | – | – | – |
| (all types) (random 0.03) | 0.09 | 0.36 | 0.21 | 0.08 | 0.06 | 0.04 | 0.06 | 0.04 |

Factors that go with more votes inside the same week (Spearman, launches de-meaned by week):

- **(all types)** (n=7696): people_self_hunted -0.41, people_hunter_age_days +0.40, hist_hunter_prior_top10_rate +0.36, people_n_makers +0.36, hist_hunter_prior_hunts +0.35, launch_n_featured_day -0.30, llm_maker_credibility +0.28, people_hunter_twitter +0.28
- **AI** (n=2214): hist_hunter_prior_hunts +0.44, people_hunter_age_days +0.43, people_self_hunted -0.41, people_n_makers +0.35, launch_n_links +0.28, people_hunter_twitter +0.28, llm_maker_credibility +0.25, launch_n_featured_day -0.25
- **Consumer** (n=303): launch_n_featured_day -0.28, hist_hunter_prior_top10_rate +0.25, people_hunter_age_days +0.24, people_hunter_twitter +0.22, people_self_hunted -0.20, people_maker_age_max_days +0.18, people_n_makers +0.15, launch_weekend +0.15
- **Design** (n=319): llm_p_top5 +0.37, people_hunter_age_days +0.35, launch_n_featured_day -0.32, people_self_hunted -0.28, llm_maker_credibility +0.28, llm_demo_wow +0.25, people_maker_age_max_days +0.23, domain_age_days +0.23
- **Developer** (n=3053): people_self_hunted -0.47, people_hunter_age_days +0.44, hist_hunter_prior_hunts +0.40, people_n_makers +0.35, llm_maker_credibility +0.33, launch_n_featured_day -0.31, people_hunter_twitter +0.31, hist_hunter_prior_top10_rate +0.29
- **Marketing & Sales** (n=299): hist_hunter_prior_top10_rate +0.33, people_hunter_age_days +0.32, hist_hunter_prior_hunts +0.29, people_self_hunted -0.26, people_n_makers +0.25, hist_maker_is_repeat +0.24, hist_maker_prior_best_rank -0.23, hist_maker_prior_launches +0.21
- **Other** (n=727): hist_hunter_prior_top10_rate +0.48, launch_n_featured_day -0.32, llm_broad_appeal +0.30, people_n_makers +0.25, llm_p_top5 +0.24, people_self_hunted -0.22, launch_hour +0.21, site_is_subdomain -0.20
- **Productivity** (n=781): launch_n_featured_day -0.33, people_self_hunted -0.29, people_n_makers +0.25, people_hunter_age_days +0.24, people_hunter_twitter +0.22, hist_maker_prior_launches +0.21, hist_maker_is_repeat +0.20, llm_p_top5 +0.18

SHAP share by source within each type (one shared model, so shares barely differ) (launches per type: {'Developer': 2006, 'AI': 1344, 'Other': 513, 'Productivity': 457, 'Design': 211, 'Consumer': 175, 'Marketing & Sales': 172}):

| type | history | people | launch | site | llm | hn | domain | github |
|---|---|---|---|---|---|---|---|---|
| AI | 35% | 24% | 22% | 8% | 7% | 3% | 2% | 0% |
| Consumer | 32% | 25% | 24% | 8% | 7% | 2% | 1% | 0% |
| Design | 32% | 25% | 25% | 8% | 7% | 3% | 1% | 0% |
| Developer | 34% | 24% | 23% | 9% | 7% | 3% | 1% | 0% |
| Marketing & Sales | 32% | 23% | 26% | 8% | 7% | 2% | 1% | 0% |
| Other | 32% | 23% | 25% | 8% | 8% | 3% | 2% | 0% |
| Productivity | 33% | 25% | 24% | 8% | 6% | 2% | 1% | 0% |

Top features per type:

- **Other**: launch_n_featured_day, people_n_makers, hist_hunter_prior_top10_rate, llm_broad_appeal, hist_maker_prior_launches, hist_hunter_prior_hunts
- **Developer**: people_n_makers, hist_hunter_prior_top10_rate, launch_n_featured_day, hist_maker_prior_launches, hist_hunter_prior_hunts, hist_maker_prior_top10_rate
- **Consumer**: people_n_makers, launch_n_featured_day, hist_hunter_prior_top10_rate, hist_maker_prior_launches, people_hunter_age_days, hist_maker_prior_top10_rate
- **AI**: hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_maker_prior_launches, hist_hunter_prior_hunts, hist_maker_prior_top10_rate
- **Marketing & Sales**: people_n_makers, hist_hunter_prior_top10_rate, launch_n_featured_day, hist_maker_prior_launches, hist_maker_prior_top10_rate, hist_hunter_prior_hunts
- **Productivity**: people_n_makers, launch_n_featured_day, hist_hunter_prior_top10_rate, hist_maker_prior_launches, people_hunter_age_days, hist_maker_prior_top10_rate
- **Design**: people_n_makers, launch_n_featured_day, hist_hunter_prior_top10_rate, hist_maker_prior_launches, people_hunter_age_days, hist_hunter_prior_hunts

## Topic lists (the model's score ranked inside each topic)

| | day@3 | day@5 | week@5 | week@10 | month@10 |
|---|---|---|---|---|---|
| Artificial Intelligence | 0.67 (0.26) | 0.73 (0.34) | 0.51 (0.07) | 0.59 (0.13) | 0.37 (0.03) |
| Productivity | 0.69 (0.33) | 0.67 (0.41) | 0.66 (0.10) | 0.68 (0.21) | 0.52 (0.05) |
| Developer Tools | 0.71 (0.35) | 0.69 (0.40) | 0.56 (0.10) | 0.67 (0.20) | 0.55 (0.05) |
| GitHub | 0.63 (0.38) | 0.56 (0.42) | 0.66 (0.18) | 0.71 (0.32) | 0.60 (0.10) |
| Open Source | 0.61 (0.38) | 0.70 (0.45) | 0.72 (0.24) | 0.70 (0.35) | 0.58 (0.14) |
| Mac | 0.53 (0.44) | 0.60 (0.50) | 0.40 (0.21) | 0.37 (0.32) | 0.60 (0.21) |
| SaaS | 0.67 (0.43) | – | 0.47 (0.22) | 0.70 (0.44) | 0.67 (0.21) |
| Marketing | 0.83 (0.50) | – | 0.80 (0.37) | – | 0.65 (0.23) |
| Design Tools | 0.50 (0.42) | – | 0.73 (0.40) | – | 0.65 (0.23) |
| API | – | – | – | – | 0.62 (0.33) |
| Menu Bar Apps | 0.67 (0.50) | – | 0.40 (0.26) | – | 0.58 (0.37) |
| Tech | 0.67 (0.50) | – | – | – | 0.68 (0.34) |
| Vercel Day | 0.67 (0.10) | 0.68 (0.17) | – | – | 0.72 (0.32) |
| iOS | 0.67 (0.43) | – | – | – | 0.73 (0.41) |
| Video | – | – | 0.80 (0.50) | – | 0.75 (0.38) |

## The lists on PH's homepage now

### yesterday (2026-10-24, 14 launches)

recall@3 0.67, recall@5 0.80, recall@10 0.80

| # | actual | predicted |
|---|---|---|
| 1 | zCAD AI | zCAD AI |
| 2 | myPip | 1Password for Agents |
| 3 | 1Password for Agents | LinkIntel |
| 4 | AgentValley | myPip |
| 5 | Canva Craft | Canva Craft |
| 6 | LinkIntel | sideOS.ai |
| 7 | Many Displays | AgentValley |
| 8 | Penta | Basedash Scheduled CSV Exports |
| 9 | Byter | Many Displays |
| 10 | Basedash Scheduled CSV Exports | How It Went |

### last week (2026-10-12, 203 launches)

recall@3 0.33, recall@5 0.80, recall@10 0.50

| # | actual | predicted |
|---|---|---|
| 1 | Pancake | Pancake |
| 2 | Jockey by TwelveLabs | NitroStack |
| 3 | Inferock | Articos MCP |
| 4 | Articos MCP | Jockey by TwelveLabs |
| 5 | Talanoa | Talanoa |
| 6 | Harness by Autonomous | Agent Vault |
| 7 | OpenCode 2.0 | MentionBird |
| 8 | Google EmbeddingGemma 2 | Ancher 2.0 |
| 9 | Inbox Zero | OpenMuse |
| 10 | NitroStack | Confidence by Spotify  |

### last month (2026-09, 708 launches)

recall@3 0.33, recall@5 0.40, recall@10 0.60

| # | actual | predicted |
|---|---|---|
| 1 | Ami AI | CREEM 2.0 |
| 2 | tiun. | Naoma AI Demo Agent V2 |
| 3 | CREEM 2.0 | Pexo |
| 4 | Clueso MCP | Hemory |
| 5 | Mastra Factory | tiun. |
| 6 | Jev | Ami AI |
| 7 | Voiskey | MCP Connectors by Databox |
| 8 | Switch | Switch |
| 9 | Naoma AI Demo Agent V2 | Mastra Factory |
| 10 | Kilo Code for JetBrains | GPT-6 Astra |

