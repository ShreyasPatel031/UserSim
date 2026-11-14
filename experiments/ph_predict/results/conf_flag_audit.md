# Confidence flag audit: share of days our pick #1 / #2 / #3 finished in the final top 3

Truth: truth_daily.json (>= 10 ranked; unranked picks = misses). 95% day-bootstrap intervals. Site figure: 90.3 / 57.0 / 41.1 (old full model, Nov 11).

| model | days | #1 top 3 | #2 top 3 | #3 top 3 | #1 top 5 | #1 top 10 |
|---|---|---|---|---|---|---|
| arm2 (published), backtest Apr-Oct 2026, 5 seeds | 184 | 70.7 [64.1, 77.2] | 57.6 [50.5, 64.7] | 45.7 [38.0, 52.7] | 87.0 [82.1, 91.8] | 93.5 [89.7, 96.7] |
| arm3, pre-registered harness 2026, 20 seeds | 184 | 75.0 [69.0, 81.0] | 56.0 [48.9, 63.0] | 38.0 [31.0, 45.1] | 88.0 [83.2, 92.4] | 96.2 [93.5, 98.9] |
| arm2, pre-registered harness 2026, 20 seeds | 184 | 72.3 [65.8, 78.8] | 56.0 [48.9, 63.0] | 44.0 [36.4, 51.1] | 86.4 [81.5, 91.3] | 93.5 [89.7, 96.7] |
| arm3, pre-registered harness 2025, 20 seeds (truth: stored dailyRank, not truth_daily.json) | 204 | 57.4 [50.5, 64.2] | 50.5 [43.6, 57.4] | 53.4 [47.1, 60.3] | 77.0 [71.1, 82.8] | 95.6 [92.6, 98.0] |
| arm2, pre-registered harness 2025, 20 seeds (truth: stored dailyRank, not truth_daily.json) | 204 | 60.3 [53.4, 66.7] | 47.5 [40.7, 54.4] | 47.5 [40.7, 54.4] | 79.9 [74.5, 85.3] | 96.6 [94.1, 99.0] |
| old full model, published 00:05 live rows | 16 | 56.2 [31.2, 81.2] | 68.8 [43.8, 87.5] | 37.5 [12.5, 62.5] | 68.8 [43.8, 87.5] | 93.8 [81.2, 100.0] |

Verdict: the flag should change. 90.3% for pick #1 is outside every interval here; arm 2 (published) gives 70.7 / 57.6 / 45.7
on 184 days. Suggested text: "#1 / #2 / #3 picks finish top 3 71% / 58% / 46% (arm 2, 184 backtest days Apr-Oct 2026)".
