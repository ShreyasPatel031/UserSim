# Product Hunt top-list prediction: backtest

7696 featured launches, 2025-10-01 to 2026-10-24. Each test month is predicted by a model trained only on earlier months (test months: 2026-06, 2026-07, 2026-08, 2026-09, 2026-10). No votes, comments or ranks of the launch itself are used as inputs.

Recall@k = share of PH's actual top k that we put in our top k. In brackets: what random picking gets. A list counts only when it has at least 2k launches (days with fewer than 20 featured launches are left out of day@10).

Data coverage (share of launches with each signal): site loaded 94%, llm scored 100%, hn story before launch 32%, domain age known 71%, github repo 0%, maker launched before 44%.

## Overall lists

| | day@3 | day@5 | day@10 | week@3 | week@5 | week@10 | month@3 | month@5 | month@10 |
|---|---|---|---|---|---|---|---|---|---|
| pre-launch | 0.66 (0.18) | 0.68 (0.25) | 0.72 (0.36) | 0.50 (0.02) | 0.58 (0.04) | 0.58 (0.07) | 0.33 (0.01) | 0.30 (0.01) | 0.38 (0.02) |
| pre-launch + all other pre-launch data | 0.62 (0.18) | 0.69 (0.25) | 0.72 (0.36) | 0.42 (0.02) | 0.59 (0.04) | 0.51 (0.07) | 0.33 (0.01) | 0.20 (0.01) | 0.33 (0.02) |
| first 4 hours | 0.65 (0.18) | 0.70 (0.25) | 0.76 (0.36) | 0.55 (0.02) | 0.65 (0.04) | 0.61 (0.07) | 0.17 (0.01) | 0.35 (0.01) | 0.50 (0.02) |
| first 4 hours + follower counts (may leak) | 0.67 (0.18) | 0.72 (0.25) | 0.78 (0.36) | 0.58 (0.02) | 0.64 (0.04) | 0.61 (0.07) | 0.33 (0.01) | 0.40 (0.01) | 0.53 (0.02) |

Headline model below: **first 4 hours**. Pre-launch = known before 00:01 PT launch (listing, team, hunter, track records). First 4 hours adds PH comments, X posts and HN stories from launch to +4 h (never votes or ranks).

95% confidence intervals (bootstrap over lists) and number of lists, headline model: day@3 0.62-0.68 (n=141); day@5 0.67-0.73 (n=126); day@10 0.74-0.79 (n=73); week@3 0.43-0.67 (n=20); week@5 0.60-0.70 (n=20); week@10 0.56-0.67 (n=20); month@3 0.00-0.33 (n=4); month@5 0.20-0.50 (n=4); month@10 0.38-0.60 (n=4).

Week and month results rest on few lists, so differences of a few points between rows below are noise.

Mean Spearman correlation with the daily order: 0.681

Per test month (each month's model learned only from earlier months):

| month | day@3 | day@5 | day@10 | week@5 | week@10 |
|---|---|---|---|---|---|
| 2026-06 | 0.63 | 0.73 | 0.78 | 0.65 | 0.62 |
| 2026-07 | 0.72 | 0.73 | 0.77 | 0.53 | 0.53 |
| 2026-08 | 0.69 | 0.69 | 0.73 | 0.70 | 0.70 |
| 2026-09 | 0.61 | 0.67 | 0.76 | 0.73 | 0.53 |
| 2026-10 | 0.58 | 0.69 | 0.77 | 0.60 | 0.45 |

## Baselines (no model)

| | day@3 | day@5 | day@10 | week@3 | week@5 | week@10 | month@3 | month@5 | month@10 |
|---|---|---|---|---|---|---|---|---|---|
| followers today (hunter+makers; leaky) | 0.45 | 0.59 | 0.71 | 0.08 | 0.18 | 0.30 | 0.00 | 0.05 | 0.10 |
| llm p_top5 alone | 0.25 | 0.40 | 0.50 | 0.03 | 0.05 | 0.09 | 0.00 | 0.00 | 0.00 |
| PH comments in first 4 h alone | 0.57 | 0.59 | 0.62 | 0.30 | 0.41 | 0.46 | 0.25 | 0.25 | 0.28 |
| look-alike earlier launches | 0.30 | 0.38 | 0.46 | 0.05 | 0.07 | 0.15 | 0.08 | 0.05 | 0.07 |

## Which sources predict: each source alone, and all sources minus one

Each source alone:

| | day@5 | day@10 | week@10 | month@10 |
|---|---|---|---|---|
| launch | 0.45 | 0.54 | 0.20 | 0.03 |
| people | 0.58 | 0.68 | 0.41 | 0.33 |
| history | 0.62 | 0.72 | 0.31 | 0.15 |
| site | 0.41 | 0.51 | 0.20 | 0.03 |
| llm | 0.40 | 0.52 | 0.11 | 0.03 |
| hn | 0.39 | 0.48 | 0.11 | 0.00 |
| domain | 0.36 | 0.49 | 0.14 | 0.03 |
| hn_day | 0.26 | 0.36 | 0.09 | 0.00 |
| github | 0.26 | 0.35 | 0.10 | 0.03 |
| product | 0.36 | 0.47 | 0.12 | 0.07 |
| yc | 0.30 | 0.37 | 0.12 | 0.07 |
| early | 0.58 | 0.63 | 0.46 | 0.28 |
| x | 0.35 | 0.45 | 0.12 | 0.05 |

All sources minus one (a drop below the full model = that source adds information):

| | day@5 | day@10 | week@10 | month@10 |
|---|---|---|---|---|
| (headline model) | 0.70 | 0.76 | 0.61 | 0.50 |
| without launch | 0.71 | 0.76 | 0.64 | 0.50 |
| without people | 0.71 | 0.77 | 0.57 | 0.45 |
| without history | 0.68 | 0.74 | 0.55 | 0.47 |
| without hn_day | 0.70 | 0.76 | 0.63 | 0.47 |
| without early | 0.67 | 0.72 | 0.56 | 0.38 |
| without x | 0.71 | 0.76 | 0.65 | 0.45 |

## Which factors matter (mean |SHAP| on held-out launches)

Share of the model's attribution by source:

| source | share |
|---|---|
| history | 31% |
| early | 24% |
| launch | 21% |
| people | 20% |
| x | 4% |
| hn_day | 0% |

Top 20 features:

| feature | mean |SHAP| |
|---|---|
| early_comments_4h | 0.1440 |
| hist_hunter_prior_top10_rate | 0.1268 |
| people_n_makers | 0.1095 |
| launch_n_featured_day | 0.0905 |
| hist_maker_prior_launches | 0.0381 |
| early_first_comment_min | 0.0373 |
| hist_maker_prior_top10_rate | 0.0332 |
| hist_hunter_prior_hunts | 0.0328 |
| people_hunter_age_days | 0.0307 |
| people_maker_age_max_days | 0.0184 |
| launch_weekday | 0.0164 |
| hist_lookalike_similarity | 0.0159 |
| x_followers_sum_log | 0.0148 |
| early_commenters_2h | 0.0121 |
| launch_link_twitter | 0.0117 |
| early_prelaunch_comments | 0.0113 |
| hist_lookalike_top10_rate | 0.0110 |
| early_comments_2h | 0.0109 |
| hist_maker_prior_best_rank | 0.0108 |
| x_followers_max_log | 0.0089 |

## How it changes by product type

Each source alone, ranking one type's launches against each other within each week (week recall@5; random in brackets):

| type | launch | people | history | site | llm | hn | domain | hn_day | github | product | yc | early | x |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Developer (random 0.08) | 0.21 | 0.34 | 0.40 | 0.16 | 0.17 | 0.15 | 0.17 | 0.10 | 0.10 | 0.16 | 0.19 | 0.47 | 0.17 |
| AI (random 0.13) | 0.26 | 0.54 | 0.31 | 0.18 | 0.18 | 0.13 | 0.17 | 0.09 | 0.09 | 0.16 | 0.11 | 0.50 | 0.18 |
| Other (random 0.29) | 0.33 | 0.53 | 0.60 | 0.40 | 0.53 | 0.47 | 0.27 | 0.33 | 0.33 | 0.33 | 0.27 | 0.53 | 0.47 |
| Productivity (random 0.23) | 0.40 | 0.33 | 0.33 | 0.27 | 0.23 | 0.27 | 0.37 | 0.27 | 0.30 | 0.40 | 0.27 | 0.40 | 0.23 |
| Design | – | – | – | – | – | – | – | – | – | – | – | – | – |
| Consumer | – | – | – | – | – | – | – | – | – | – | – | – | – |
| Marketing & Sales | – | – | – | – | – | – | – | – | – | – | – | – | – |
| (all types) (random 0.04) | 0.11 | 0.40 | 0.25 | 0.08 | 0.06 | 0.04 | 0.04 | 0.03 | 0.05 | 0.05 | 0.09 | 0.35 | 0.09 |

Factors that go with more votes inside the same week (Spearman, launches de-meaned by week):

- **(all types)** (n=7696): early_comments_4h +0.49, early_commenters_2h +0.43, early_comments_2h +0.43, people_self_hunted -0.41, people_hunter_age_days +0.40, hist_hunter_prior_top10_rate +0.36, people_n_makers +0.36, hist_hunter_prior_hunts +0.35
- **AI** (n=2214): early_comments_4h +0.51, early_comments_2h +0.48, early_commenters_2h +0.48, hist_hunter_prior_hunts +0.44, people_hunter_age_days +0.43, people_self_hunted -0.41, early_hours_to_20th -0.39, early_comments_1h +0.38
- **Consumer** (n=303): early_comments_4h +0.34, early_comments_2h +0.29, early_commenters_2h +0.29, launch_n_featured_day -0.28, hist_hunter_prior_top10_rate +0.25, people_hunter_age_days +0.24, people_hunter_twitter +0.22, early_comments_1h +0.20
- **Design** (n=319): people_hunter_age_days +0.35, early_comments_4h +0.33, launch_n_featured_day -0.32, people_self_hunted -0.28, early_commenters_2h +0.27, early_comments_2h +0.27, people_maker_age_max_days +0.23, hist_hunter_prior_hunts +0.22
- **Developer** (n=3053): early_comments_4h +0.48, people_self_hunted -0.47, people_hunter_age_days +0.44, early_commenters_2h +0.42, early_comments_2h +0.42, hist_hunter_prior_hunts +0.40, people_n_makers +0.35, early_comments_1h +0.31
- **Marketing & Sales** (n=299): early_comments_4h +0.48, early_comments_2h +0.39, early_commenters_2h +0.39, early_hours_to_20th -0.34, hist_hunter_prior_top10_rate +0.33, early_first_comment_min -0.32, people_hunter_age_days +0.32, early_comments_1h +0.30
- **Other** (n=727): hist_hunter_prior_top10_rate +0.48, early_comments_4h +0.35, launch_n_featured_day -0.32, early_comments_2h +0.30, early_commenters_2h +0.29, people_n_makers +0.25, people_self_hunted -0.22, early_comments_1h +0.22
- **Productivity** (n=781): launch_n_featured_day -0.33, early_comments_4h +0.33, people_self_hunted -0.29, early_first_comment_min -0.26, people_n_makers +0.25, people_hunter_age_days +0.24, early_commenters_2h +0.23, early_comments_2h +0.23

SHAP share by source within each type (one shared model, so shares barely differ) (launches per type: {'Developer': 1377, 'AI': 902, 'Productivity': 313, 'Other': 200, 'Design': 139, 'Consumer': 124, 'Marketing & Sales': 97}):

| type | history | early | launch | people | x | hn_day |
|---|---|---|---|---|---|---|
| AI | 32% | 25% | 20% | 19% | 4% | 0% |
| Consumer | 29% | 21% | 24% | 21% | 4% | 0% |
| Design | 28% | 22% | 24% | 21% | 4% | 0% |
| Developer | 32% | 23% | 21% | 20% | 4% | 0% |
| Marketing & Sales | 29% | 26% | 22% | 18% | 4% | 0% |
| Other | 31% | 24% | 20% | 19% | 5% | 0% |
| Productivity | 30% | 23% | 23% | 21% | 4% | 0% |

Top features per type:

- **Developer**: early_comments_4h, hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_maker_prior_launches, early_first_comment_min
- **Productivity**: early_comments_4h, people_n_makers, hist_hunter_prior_top10_rate, launch_n_featured_day, early_first_comment_min, hist_maker_prior_launches
- **AI**: early_comments_4h, hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_maker_prior_launches, hist_maker_prior_top10_rate
- **Consumer**: early_comments_4h, people_n_makers, launch_n_featured_day, hist_hunter_prior_top10_rate, early_first_comment_min, people_hunter_age_days
- **Marketing & Sales**: early_comments_4h, hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, hist_maker_prior_launches, hist_maker_prior_top10_rate
- **Other**: early_comments_4h, hist_hunter_prior_top10_rate, people_n_makers, launch_n_featured_day, early_first_comment_min, hist_maker_prior_launches
- **Design**: early_comments_4h, people_n_makers, hist_hunter_prior_top10_rate, launch_n_featured_day, early_first_comment_min, hist_maker_prior_launches

## Topic lists (the model's score ranked inside each topic)

| | day@3 | day@5 | week@5 | week@10 | month@10 |
|---|---|---|---|---|---|
| Artificial Intelligence | 0.71 (0.27) | 0.77 (0.35) | 0.62 (0.07) | 0.63 (0.14) | 0.45 (0.03) |
| Productivity | 0.70 (0.33) | 0.69 (0.42) | 0.72 (0.11) | 0.74 (0.22) | 0.70 (0.05) |
| Developer Tools | 0.77 (0.35) | 0.78 (0.40) | 0.65 (0.10) | 0.71 (0.21) | 0.60 (0.06) |
| GitHub | 0.59 (0.38) | 0.68 (0.42) | 0.78 (0.18) | 0.72 (0.31) | 0.68 (0.11) |
| Open Source | 0.65 (0.38) | 0.80 (0.45) | 0.73 (0.23) | 0.72 (0.33) | 0.70 (0.16) |
| Mac | 0.48 (0.43) | 0.80 (0.50) | 0.50 (0.21) | 0.47 (0.32) | 0.72 (0.21) |
| SaaS | 0.67 (0.42) | – | 0.50 (0.23) | 0.70 (0.45) | 0.70 (0.22) |
| Design Tools | 0.44 (0.43) | – | 0.80 (0.37) | – | 0.70 (0.26) |
| Marketing | 1.00 (0.50) | – | 0.80 (0.32) | – | 0.72 (0.26) |
| Menu Bar Apps | 0.67 (0.50) | – | 0.60 (0.26) | – | 0.68 (0.37) |
| Vercel Day | 0.78 (0.07) | 0.73 (0.13) | – | – | 0.63 (0.24) |
| API | – | – | – | – | 0.68 (0.36) |
| OpenAI Day | 0.83 (0.05) | 0.80 (0.08) | – | – | 0.90 (0.15) |
| Tech | – | – | – | – | 0.73 (0.36) |
| iOS | 0.67 (0.43) | – | – | – | 0.85 (0.40) |

## The lists on PH's homepage now

### yesterday (2026-10-24, 14 launches)

recall@3 1.00, recall@5 0.80, recall@10 0.80

| # | actual | predicted |
|---|---|---|
| 1 | zCAD AI | zCAD AI |
| 2 | myPip | 1Password for Agents |
| 3 | 1Password for Agents | myPip |
| 4 | AgentValley | LinkIntel |
| 5 | Canva Craft | AgentValley |
| 6 | LinkIntel | Canva Craft |
| 7 | Many Displays | Penta |
| 8 | Penta | sideOS.ai |
| 9 | Byter | Basedash Scheduled CSV Exports |
| 10 | Basedash Scheduled CSV Exports | Shedi |

### last week (2026-10-12, 203 launches)

recall@3 0.33, recall@5 0.60, recall@10 0.50

| # | actual | predicted |
|---|---|---|
| 1 | Pancake | Pancake |
| 2 | Jockey by TwelveLabs | NitroStack |
| 3 | Inferock | Articos MCP |
| 4 | Articos MCP | Jockey by TwelveLabs |
| 5 | Talanoa | SignWith |
| 6 | Harness by Autonomous | MyLens |
| 7 | OpenCode 2.0 | AdAnt 2.0 |
| 8 | Google EmbeddingGemma 2 | Talanoa |
| 9 | Inbox Zero | Kai |
| 10 | NitroStack | PostNitro for Agents |

### last month (2026-09, 708 launches)

recall@3 0.33, recall@5 0.60, recall@10 0.60

| # | actual | predicted |
|---|---|---|
| 1 | Ami AI | CREEM 2.0 |
| 2 | tiun. | Naoma AI Demo Agent V2 |
| 3 | CREEM 2.0 | Clueso MCP |
| 4 | Clueso MCP | Ami AI |
| 5 | Mastra Factory | Pexo |
| 6 | Jev | Hemory |
| 7 | Voiskey | MCP Connectors by Databox |
| 8 | Switch | Anysite.io |
| 9 | Naoma AI Demo Agent V2 | Mastra Factory |
| 10 | Kilo Code for JetBrains | tiun. |

