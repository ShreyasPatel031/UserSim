# Topic momentum at 00:05 inside arm 2 (14:00Z Nov 14; held data; CLOSED, no gain)

Not run before: lm_breakout.py C1 (Nov 11, af750c46) tested a short d-8..d-2 / d-14..d-7 topic window on the honest LM (-0.8 [-2.5, +0.7]
top 3). New here: 30/90-day windows, share trend, line-up share, topic x weekday, 2025 + 2026 history, inside arm 2.
Features (topic_momentum.py, 15 per launch, 11,966 launches 2025-01-01 .. 2026-11-13): per topic, shrunk mean within-day-relative log
votes and top-10 rate over d-31..d-2 and d-91..d-2 (labels only from days <= d-2: closed and settled), line-up share trend
(d-30..d-1 vs d-120..d-31), same-weekday top-10 rate (d-91..d-2), the day's own line-up share; max and mean over the launch's topics.
Harness: history_retrain.py JOINT=1 JOINT_KEEP_2025=1 (features on 2025 rows too), ARM=2, month-forward, 5 seeds; baseline arm 2
(decomp 'both') reproduces 60.7 / 68.4 / 75.7 on 214 days. Paired 10,000-draw day bootstrap.

| cut | arm 2 | + topic (all 15) | diff top 3 / 5 / 10 | + topic without day_share | diff |
|---|---|---|---|---|---|
| >= 10 ranked (183 d) | 58.1 / 65.2 / 76.9 | 56.8 / 64.9 / 76.4 | -1.3 [-3.1, +0.5] / -0.3 [-1.5, +0.9] / -0.4 [-1.1, +0.2] | 57.4 / 65.5 / 76.4 | -0.7 [-2.4, +0.9] / +0.2 [-1.1, +1.5] / -0.5 [-1.2, +0.2] |
| all 214 | 60.7 / 68.4 / 75.7 | 59.2 / 67.9 / 75.3 | -1.6 [-3.3, +0.0] / -0.6 [-1.7, +0.6] / -0.4 [-0.9, +0.2] | 59.3 / 68.5 / 75.3 | -1.4 [-3.0, +0.2] / +0.1 [-1.0, +1.2] / -0.4 [-1.0, +0.2] |
| last 90 of >= 10 | 58.1 / 66.7 / 77.9 | 57.0 / 66.2 / 77.7 | -1.1 [-3.0, +0.7] / -0.4 [-2.2, +1.3] / -0.2 [-1.0, +0.6] | 57.8 / 67.1 / 77.7 | -0.4 [-2.2, +1.5] / +0.4 [-1.1, +2.0] / -0.2 [-1.0, +0.6] |

Decision (rule 5): no cut clear of 0 in favour; all top-3 point estimates negative. Closed. The day_share columns (same-day crowding,
the orchestrator subagent's area) were run separately only to keep the two apart; they do not change the verdict.
