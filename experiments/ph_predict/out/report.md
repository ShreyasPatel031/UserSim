# Product Hunt top-list prediction: backtest

3933 featured launches, 2026-03-01 to 2026-10-24. Each test month is predicted by a model trained only on earlier months (test months: 2026-05, 2026-06, 2026-07, 2026-08, 2026-09, 2026-10). No votes, comments or ranks of the launch itself are used as inputs.

Recall@k = share of PH's actual top k that we put in our top k. In brackets: what random picking gets.

Data coverage (share of launches with each signal): site loaded 88%, llm scored 90%, hn story before launch 29%, domain age known 66%, github repo 0%, maker launched before 40%.

## Overall lists

| | day@3 | day@5 | day@10 | week@3 | week@5 | week@10 | month@3 | month@5 | month@10 |
|---|---|---|---|---|---|---|---|---|---|
| model (headline: no follower counts) | 0.59 (0.18) | 0.65 (0.25) | 0.73 (0.36) | 0.44 (0.02) | 0.47 (0.04) | 0.52 (0.07) | 0.47 (0.01) | 0.36 (0.01) | 0.36 (0.03) |
| model + today's follower counts (may leak) | 0.61 (0.18) | 0.67 (0.25) | 0.76 (0.36) | 0.40 (0.02) | 0.45 (0.04) | 0.54 (0.07) | 0.40 (0.01) | 0.40 (0.01) | 0.38 (0.03) |

Mean Spearman correlation with the daily order: 0.604

## Baselines (no model)

| | day@3 | day@5 | day@10 | week@3 | week@5 | week@10 | month@3 | month@5 | month@10 |
|---|---|---|---|---|---|---|---|---|---|
| followers today (hunter+makers; leaky) | 0.45 | 0.58 | 0.70 | 0.08 | 0.17 | 0.29 | 0.00 | 0.04 | 0.12 |
| llm p_top5 alone | 0.26 | 0.40 | 0.50 | 0.02 | 0.02 | 0.10 | 0.00 | 0.00 | 0.00 |
| look-alike earlier launches | 0.30 | 0.37 | 0.46 | 0.02 | 0.07 | 0.15 | 0.00 | 0.04 | 0.02 |

## Which sources predict: each source alone, and all sources minus one

Each source alone:

| | day@5 | day@10 | week@10 | month@10 |
|---|---|---|---|---|
| launch | 0.45 | 0.52 | 0.20 | 0.06 |
| people | 0.58 | 0.68 | 0.36 | 0.32 |
| history | 0.62 | 0.70 | 0.29 | 0.12 |
| site | 0.41 | 0.49 | 0.20 | 0.06 |
| llm | 0.40 | 0.49 | 0.12 | 0.04 |
| hn | 0.35 | 0.43 | 0.09 | 0.06 |
| domain | 0.35 | 0.46 | 0.12 | 0.06 |
| github | 0.25 | 0.36 | 0.07 | 0.04 |

All sources minus one (a drop below the full model = that source adds information):

| | day@5 | day@10 | week@10 | month@10 |
|---|---|---|---|---|
| (full model) | 0.65 | 0.73 | 0.52 | 0.36 |
| without launch | 0.65 | 0.71 | 0.52 | 0.40 |
| without people | 0.63 | 0.72 | 0.35 | 0.10 |
| without history | 0.60 | 0.70 | 0.40 | 0.24 |
| without site | 0.65 | 0.71 | 0.54 | 0.36 |
| without llm | 0.65 | 0.72 | 0.51 | 0.34 |
| without hn | 0.65 | 0.72 | 0.53 | 0.34 |
| without domain | 0.65 | 0.72 | 0.54 | 0.38 |
| without github | 0.65 | 0.72 | 0.53 | 0.36 |

## Which factors matter (mean |SHAP| on held-out launches)

Share of the model's attribution by source:

| source | share |
|---|---|
| history | 34% |
| launch | 23% |
| people | 20% |
| site | 10% |
| llm | 9% |
| domain | 2% |
| hn | 2% |
| github | 0% |

Top 20 features:

| feature | mean |SHAP| |
|---|---|
| hist_hunter_prior_top10_rate | 0.1344 |
| people_n_makers | 0.1133 |
| launch_n_featured_day | 0.0942 |
| hist_hunter_prior_hunts | 0.0774 |
| people_hunter_age_days | 0.0371 |
| hist_maker_prior_launches | 0.0291 |
| site_w_ai | 0.0259 |
| llm_p_top5 | 0.0247 |
| launch_n_links | 0.0204 |
| hist_maker_prior_top10_rate | 0.0202 |
| llm_broad_appeal | 0.0200 |
| people_maker_age_max_days | 0.0183 |
| domain_age_days | 0.0178 |
| site_words_log | 0.0174 |
| hist_topic_top10_rate_max | 0.0162 |
| people_self_hunted | 0.0160 |
| launch_weekday | 0.0153 |
| hist_lookalike_similarity | 0.0144 |
| launch_n_media | 0.0136 |
| hist_maker_prior_best_rank | 0.0135 |

## How it changes by product type

Each source alone, ranking one type's launches against each other within each week (week recall@5; random in brackets):

| type | launch | people | history | site | llm | hn | domain | github |
|---|---|---|---|---|---|---|---|---|
| Developer (random 0.08) | 0.16 | 0.30 | 0.35 | 0.18 | 0.13 | 0.07 | 0.13 | 0.05 |
| Other (random 0.29) | 0.47 | 0.53 | 0.60 | 0.47 | 0.40 | 0.53 | 0.27 | 0.27 |
| AI (random 0.13) | 0.28 | 0.48 | 0.32 | 0.20 | 0.18 | 0.13 | 0.16 | 0.12 |
| Design | – | – | – | – | – | – | – | – |
| Consumer | – | – | – | – | – | – | – | – |
| Productivity (random 0.23) | 0.33 | 0.30 | 0.33 | 0.27 | 0.30 | 0.20 | 0.27 | 0.23 |
| Marketing & Sales | – | – | – | – | – | – | – | – |
| (all types) (random 0.04) | 0.10 | 0.35 | 0.17 | 0.09 | 0.07 | 0.05 | 0.08 | 0.02 |

Factors that go with more votes inside the same week (Spearman, launches de-meaned by week):

- **(all types)** (n=3933): people_self_hunted -0.47, people_hunter_age_days +0.46, hist_hunter_prior_hunts +0.40, people_n_makers +0.36, launch_n_featured_day -0.34, people_hunter_twitter +0.32, llm_maker_credibility +0.31, hist_hunter_prior_top10_rate +0.30
- **AI** (n=1157): people_hunter_age_days +0.46, people_self_hunted -0.45, hist_hunter_prior_hunts +0.45, people_n_makers +0.38, people_hunter_twitter +0.32, launch_n_featured_day -0.31, launch_n_links +0.29, hist_hunter_prior_top10_rate +0.28
- **Consumer** (n=143): people_self_hunted -0.36, launch_n_featured_day -0.29, launch_n_links +0.28, hist_maker_prior_launches +0.27, hist_maker_is_repeat +0.27, people_n_makers +0.21, site_w_testimonial -0.20, llm_p_top5 +0.20
- **Design** (n=160): launch_n_featured_day -0.42, llm_p_top5 +0.36, launch_n_links +0.36, launch_link_twitter +0.35, llm_demo_wow +0.32, people_hunter_age_days +0.29, llm_maker_credibility +0.25, llm_broad_appeal +0.24
- **Developer** (n=1723): people_self_hunted -0.49, people_hunter_age_days +0.46, hist_hunter_prior_hunts +0.41, launch_n_featured_day -0.37, people_n_makers +0.37, people_hunter_twitter +0.34, hist_maker_is_repeat +0.32, llm_maker_credibility +0.31
- **Marketing & Sales** (n=121): people_self_hunted -0.41, people_hunter_age_days +0.38, hist_hunter_prior_hunts +0.35, people_n_makers +0.34, launch_n_media +0.32, hist_maker_is_repeat +0.31, llm_polish +0.30, llm_p_top5 +0.30
- **Other** (n=245): hist_hunter_prior_hunts +0.40, hist_hunter_prior_top10_rate +0.39, people_hunter_age_days +0.36, people_self_hunted -0.34, launch_n_featured_day -0.31, llm_broad_appeal +0.29, llm_p_top5 +0.27, site_is_subdomain -0.26
- **Productivity** (n=384): launch_n_featured_day -0.38, hist_hunter_prior_top10_rate +0.36, people_self_hunted -0.26, people_hunter_age_days +0.23, people_hunter_twitter +0.20, people_n_makers +0.19, launch_topic_vercel_day -0.18, launch_topic_openai_day -0.18

SHAP share by source within each type (one shared model, so shares barely differ) (launches per type: {'Developer': 1439, 'AI': 941, 'Productivity': 325, 'Other': 208, 'Design': 144, 'Consumer': 129, 'Marketing & Sales': 103}):

| type | history | launch | people | site | llm | domain | hn | github |
|---|---|---|---|---|---|---|---|---|
| AI | 35% | 21% | 20% | 10% | 9% | 2% | 2% | 0% |
| Consumer | 31% | 25% | 21% | 10% | 9% | 2% | 2% | 0% |
| Design | 31% | 24% | 21% | 10% | 10% | 2% | 2% | 0% |
| Developer | 34% | 23% | 20% | 10% | 8% | 2% | 2% | 0% |
| Marketing & Sales | 32% | 26% | 19% | 11% | 9% | 2% | 2% | 0% |
| Other | 34% | 22% | 21% | 10% | 10% | 2% | 2% | 0% |
| Productivity | 32% | 26% | 20% | 11% | 9% | 2% | 2% | 0% |

Top features per type:

- **Other**: hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, hist_maker_prior_launches
- **AI**: hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, hist_maker_prior_launches
- **Productivity**: hist_hunter_prior_top10_rate, launch_n_featured_day, people_n_makers, hist_hunter_prior_hunts, people_hunter_age_days, site_w_ai
- **Consumer**: hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, site_w_ai
- **Developer**: hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, hist_maker_prior_launches
- **Marketing & Sales**: hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, hist_maker_prior_launches
- **Design**: hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_hunter_prior_hunts, people_hunter_age_days, llm_p_top5

## Topic lists (the model's score ranked inside each topic)

| | day@3 | day@5 | week@5 | week@10 | month@10 |
|---|---|---|---|---|---|
| Artificial Intelligence | 0.66 (0.27) | 0.71 (0.35) | 0.48 (0.07) | 0.60 (0.14) | 0.42 (0.05) |
| Productivity | 0.65 (0.34) | 0.64 (0.42) | 0.75 (0.11) | 0.69 (0.22) | 0.60 (0.08) |
| Developer Tools | 0.73 (0.35) | 0.71 (0.40) | 0.57 (0.10) | 0.69 (0.21) | 0.58 (0.09) |
| GitHub | 0.58 (0.38) | 0.56 (0.42) | 0.72 (0.18) | 0.71 (0.31) | 0.62 (0.18) |
| Open Source | 0.65 (0.38) | 0.73 (0.45) | 0.72 (0.24) | 0.70 (0.33) | 0.60 (0.16) |
| Mac | 0.52 (0.43) | 0.40 (0.50) | 0.35 (0.21) | 0.33 (0.32) | 0.57 (0.21) |
| SaaS | 0.58 (0.42) | – | 0.50 (0.23) | 0.70 (0.45) | 0.68 (0.22) |
| Design Tools | 0.44 (0.43) | – | 0.70 (0.37) | – | 0.70 (0.26) |
| Marketing | 1.00 (0.50) | – | 0.80 (0.32) | – | 0.60 (0.26) |
| Menu Bar Apps | 0.67 (0.50) | – | 0.40 (0.26) | – | 0.55 (0.37) |
| API | – | – | – | – | 0.65 (0.36) |
| Vercel Day | 0.89 (0.07) | 0.60 (0.13) | – | – | 0.70 (0.24) |
| OpenAI Day | 0.83 (0.05) | 0.60 (0.08) | – | – | 0.80 (0.15) |
| Tech | – | – | – | – | 0.67 (0.36) |
| iOS | 0.67 (0.43) | – | – | – | 0.80 (0.40) |

## The lists on PH's homepage now

### yesterday (2026-10-24, 14 launches)

recall@3 1.00, recall@5 0.80, recall@10 0.90

| # | actual | predicted |
|---|---|---|
| 1 | zCAD AI | zCAD AI |
| 2 | myPip | 1Password for Agents |
| 3 | 1Password for Agents | myPip |
| 4 | AgentValley | LinkIntel |
| 5 | Canva Craft | Canva Craft |
| 6 | LinkIntel | sideOS.ai |
| 7 | Many Displays | Many Displays |
| 8 | Penta | Basedash Scheduled CSV Exports |
| 9 | Byter | Byter |
| 10 | Basedash Scheduled CSV Exports | AgentValley |

### last week (2026-10-12, 203 launches)

recall@3 0.67, recall@5 0.60, recall@10 0.50

| # | actual | predicted |
|---|---|---|
| 1 | Pancake | Pancake |
| 2 | Jockey by TwelveLabs | NitroStack |
| 3 | Inferock | Jockey by TwelveLabs |
| 4 | Articos MCP | Articos MCP |
| 5 | Talanoa | Navige |
| 6 | Harness by Autonomous | Notion: Context for your agents |
| 7 | OpenCode 2.0 | MentionBird |
| 8 | Google EmbeddingGemma 2 | Talanoa |
| 9 | Inbox Zero | Confidence by Spotify  |
| 10 | NitroStack | Ancher 2.0 |

### last month (2026-09, 708 launches)

recall@3 0.67, recall@5 0.40, recall@10 0.40

| # | actual | predicted |
|---|---|---|
| 1 | Ami AI | CREEM 2.0 |
| 2 | tiun. | Ami AI |
| 3 | CREEM 2.0 | MCP Connectors by Databox |
| 4 | Clueso MCP | Hemory |
| 5 | Mastra Factory | Weave Router 2.0 |
| 6 | Jev | Clueso MCP |
| 7 | Voiskey | Humalike - AI NPC |
| 8 | Switch | tiun. |
| 9 | Naoma AI Demo Agent V2 | Monid |
| 10 | Kilo Code for JetBrains | Pexo |

