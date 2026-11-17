# Within-day ranking objective vs regression for arm 3 — closed, none clears

Pre-registered in `PREREG.md` (commit 8f17acf9) before any run.

**Setup.**
- Arm-3 inputs, fitted month-forward on Apr–Nov 2026.
- 5 seeds per arm, `TW.P0` settings.
- Scored on 195 days (Apr 1 – Nov 12; 5,197 ranked launches).
- Day bootstrap with 2,000 draws.

Scripts: `ro_run.py` fits the arms; `score.py` writes `result.json`.

## Lines

| arm | top 3 | top 5 | top 10 | Spearman of daily top 10 |
|---|---|---|---|---|
| arm 3 (regression on log votes, 5 seeds) | 56.8 [53.5, 60.0] | 64.9 [62.4, 67.3] | 77.7 [76.1, 79.4] | 0.551 [0.514, 0.584] |
| (a) lambdarank, relevance 11 − r for the top 10 | 56.4 [53.2, 59.5] | 65.9 [63.6, 68.4] | 77.1 [75.3, 78.8] | 0.556 |
| (b) rank_xendcg, same labels | 56.1 [53.0, 59.1] | 64.7 [62.4, 67.1] | 76.3 [74.5, 78.2] | 0.550 |
| (c) regression on within-day percentile | 55.7 [52.5, 58.8] | 65.0 [62.4, 67.7] | 77.7 [76.2, 79.3] | 0.538 |
| (d) 50/50 rank average of arm 3 and (a) | 56.8 [53.5, 60.0] | 65.2 [62.7, 67.6] | 77.5 [75.9, 79.2] | 0.548 |

## Paired differences vs arm 3

| arm | top 3 | top 5 | top 10 | Spearman |
|---|---|---|---|---|
| (a) | −0.3 [−2.6, +1.9] | +1.0 [−0.3, +2.4] | −0.7 [−1.5, +0.1] | +0.005 [−0.008, +0.018] |
| (b) | −0.7 [−3.1, +1.5] | −0.2 [−1.7, +1.3] | **−1.4 [−2.4, −0.6]** | −0.001 [−0.017, +0.016] |
| (c) | −1.0 [−3.4, +1.2] | +0.1 [−1.5, +1.6] | +0.0 [−0.8, +0.8] | −0.013 [−0.029, +0.003] |
| (d) | +0.0 [−1.4, +1.4] | +0.3 [−0.4, +1.0] | −0.2 [−0.7, +0.3] | −0.003 [−0.009, +0.003] |

## Decision

- No arm clears under the pre-registered rule (a lower bound above 0 on some cut, with no other cut's upper bound below 0).
- xendcg loses at top 10.
- **The question is closed, and there is no patch for the PH agent.**
- Changing the objective does not move top 3. The weakness at top 3 is in the inputs, not the loss: regression on log votes already orders the top of each day as well as a direct ranking loss does.

**Leak checks.** Same as the rebuild:
- inputs are dated before 00:05 of each launch day;
- training rows come strictly from earlier months;
- test-day ranks are used only for scoring.
