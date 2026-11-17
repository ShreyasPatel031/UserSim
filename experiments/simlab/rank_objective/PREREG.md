# Pre-registration: within-day ranking objective vs regression for arm 3

Orchestrator 10:18Z Nov 17. Written and committed before any run.

## Setup
- **Data:** arm-3 rebuild inputs: `X_full.parquet` (arm-2 `TW.prep`) plus the E5 A/B/C feature table. These are the same columns as `midnight_anatomy/arm3_oos.py`.
- **Folds:** month-forward, test months Apr–Nov 2026, each trained on all earlier rows.
- **Scored days:** the 195 days of the midnight anatomy (2026-04-01 – 2026-11-12, at least 10 ranked launches).
- **Seeds:** 5 per arm (0–4), predictions averaged. LightGBM settings are `TW.P0` (400 trees, lr 0.03, 15 leaves, …) for every arm. Only the objective, and for (a)/(b) the day grouping, change.

## Training rank
`r` = the final `dailyRank` when present. Otherwise it is the within-day rank by final votes, among that day's training rows (ties averaged, then rounded up). `n_day` = the number of rows that day.

## Arms
- **arm 3 (reference):** LGBMRegressor on log1p(votes), as published, re-fit with the same 5 seeds.
- **(a) lambdarank:** grouped by day. Relevance is `11 − r` for r ≤ 10 (so rank 1 → 10 … rank 10 → 1) and 0 otherwise. This deviates slightly from "10 − rank" so that rank 10 is not 0. `label_gain` is the identity 0..10.
- **(b) rank_xendcg:** same groups and labels as (a).
- **(c) regression on within-day percentile:** target `1 − (r − 1)/(n_day − 1)`.
- **(d) 50/50 rank average:** the mean of the within-day rank of arm 3 and of (a), on the test day. Ties are broken by arm 3.

## Metrics
- Top 3 / 5 / 10 hits per day: |predicted top k ∩ actual top k| / k × 100.
- Mean over days, with a 2,000-draw day bootstrap.
- Paired difference (arm − arm 3) per day, with a day-bootstrap 95% interval.
- Spearman of the daily top 10: on each day, the Spearman between the arm's score and the actual rank, over that day's actual top 10. Reported as the mean over days with a bootstrap interval, plus the paired difference.

## Decision rule
- An arm **clears** if, on at least one of top 3 / 5 / 10, its paired lower bound is > 0, and on no other cut is its paired upper bound < 0.
- If one or more arms clear, the best by the top-3 paired mean gets a rehearsal-ready patch for the PH agent under the models rule.
- If none clears, the question is closed.
- No other arms, mappings or windows will be added after seeing results. Any extra analysis will be labelled exploratory.

## Leak checks (same as the rebuild)
- Inputs are dated before 00:05 of the launch day.
- Month-forward: training rows are strictly in earlier months.
- Test-day labels are used only for scoring.
