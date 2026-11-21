# North star: calibrated simulated users (set Nov 21 2026, from Shreyas's direction)

The product is the user-testing platform. The north star is whether the simulated users are calibrated to real humans on
three axes. Product Hunt (launch outcomes, voters and commenters) and real human computer-use traces are the ground truth.
Shreyas wants models trained on this data as soon as it is calibrated, so data quality comes first.

## The three metrics (pre-registered; thresholds proposed by the orchestrator, Shreyas may amend)

| Axis | Question | Metric(s) | "Calibrated" threshold | Owner |
|---|---|---|---|---|
| WHO | Did we choose the right representative people? | Segment-mix Jensen–Shannon distance, predicted vs real backer and commenter cohort (median over launches); backer recall@N vs the most-active baseline | JS <= 0.10, and recall@N >= 2x the baseline with the 95% interval clear of it | E5 |
| WHAT | Do we predict what they say? | Broad-theme recall and precision vs real comment themes; specific-issue recall vs a plain-prompt baseline; sentiment distribution distance (scored on predicted reactions only, not on concern or question lists; decided Nov 21); vote-probability calibration (ECE, Brier) | Broad recall >= 70% with precision >= 50%; specific-issue recall above the plain-prompt baseline, interval clear; sentiment distance <= 0.10; ECE <= 0.05 | E5 + plugin |
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

## Human-behaviour datasets for HOW (orchestrator research, Nov 21; [U] = not verified on the dataset page)
| Use | Dataset | Why | Licence |
|---|---|---|---|
| Timing, dwell, pointer | CUA-Suite / VideoCUA (ServiceNow, 2026): ~10K tasks, 55 h video, ms-timestamped clicks, scrolls, keys and cursor paths, 87 desktop apps | Richest pacing signal; instructed experts | MIT on HF (paper says CC BY 4.0) |
| Long flows, errors kept | AgentNet / OpenCUA: 22.6K trajectories, ~420K steps, 200+ apps and sites | Largest CUA set; mouse timing reduced away | MIT |
| Web action sequences | Mind2Web (+ multimodal; the raw dump has Playwright traces, HAR and video) | Matched web tasks | CC BY 4.0, research only, so EVAL ONLY |
| Natural abandonment at scale | OTTO: 14.6M real shopper sessions, 230M timestamped events | Real give-up behaviour (cart without order) | CC BY 4.0 |
| Search, click, leave | Coveo SIGIR eCom 2021: ~5M sessions, ms timestamps | Natural browse and abandon | Research only, so EVAL ONLY |
| Typing speed | Aalto 136M keystrokes (168K people) | Per-key timing | Scientific use only |
| Mobile | AITW (715K episodes), AndroidControl, GUI-Odyssey | Instructed mobile flows | AITW licence not stated [U]; GUI-Odyssey CC BY 4.0 |
| Not usable for training | WebLINX | | CC BY-NC-SA |

Gap no dataset covers: a natural, unscripted first-time product trial with screen, pointer and timing, real abandonment, and
who the user is. That is our data (Screenpipe, plus calibrated simulated runs scored against real cohorts), and it is the IP.
