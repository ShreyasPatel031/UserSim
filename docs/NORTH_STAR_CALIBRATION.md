# North star: calibrated simulated users (set Nov 21 2026, from Shreyas's direction)

The product is the user-testing platform. The north star is whether the simulated users are calibrated to real humans on
three axes. Product Hunt (launch outcomes, voters and commenters) and real human computer-use traces are the ground truth.
Shreyas wants models trained on this data as soon as it is calibrated, so data quality comes first.

## The three metrics (pre-registered; thresholds proposed by the orchestrator, Shreyas may amend)

| Axis | Question | Metric(s) | "Calibrated" threshold | Owner |
|---|---|---|---|---|
| WHO | Did we choose the right representative people? | Segment-mix Jensen–Shannon distance, predicted vs real backer and commenter cohort (median over launches); backer recall@N vs the most-active baseline | JS <= 0.10, and recall@N >= 2x the baseline with the 95% interval clear of it | E5 |
| WHAT | Do we predict what they say? | Broad-theme recall and precision vs real comment themes; specific-issue recall vs a plain-prompt baseline; sentiment distribution distance; vote-probability calibration (ECE, Brier) | Broad recall >= 70% with precision >= 50%; specific-issue recall above the plain-prompt baseline, interval clear; sentiment distance <= 0.10; ECE <= 0.05 | E5 + plugin |
| HOW | Do they use the product like a human? | Per-metric distance to real human traces on matched tasks (action mix JS; inter-action time, dwell and scroll KS; backtrack and error rates; give-up rate); plus a classifier telling sim from human traces | Action-mix JS <= 0.10; timing KS <= 0.15; give-up rate within 5 points of human; human-vs-sim classifier AUC <= 0.65 | plugin |

- **Calibrated** = all three axes meet their thresholds on 7 consecutive scored days, counting live days and backtest
  batches scored that day. Every number is reported with its n, coverage and 95% interval.
- When that holds, the orchestrator tells Shreyas, and the trace store's current version is frozen as training dataset v1.

## Guard
- The website's published forecast score must not fall sharply. If its rolling 7-day value is more than 5 points below its
  30-day value, the PH agent alerts the same day with a diagnosis of which input or calibration changed.

## Budget
- Simulated-user runs: $50–100 per day in total. Daily Product Hunt launches come first; backtest launches fill the rest. The
  loop each day is: calibrate, tune, then run the next batch.

## Ground truth sources
- Product Hunt: results/calibration/<day>/ (lineup_frozen, truth.json) and results/calibration/backtest_v1/ (Oct 22–Nov 20).
- Human traces: Mind2Web human action traces (Online-Mind2Web has only step counts), the shortlist of the largest
  human computer-use datasets (orchestrator research, pending), and Shreyas's Screenpipe features (private bucket; derived
  features only).
