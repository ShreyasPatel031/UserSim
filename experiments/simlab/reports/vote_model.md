# E1 v1: generative vote model with the pool as one audience (Nov 2, 2026)

Code: `simlab/vote_model.py`. Pre-launch only (Shreyas, Nov 2). Votes of launch i are modelled as a sum of audiences:
`mu_i = a * S_i + sum_k size_ik * conv_k(z_i) + browse_i`, where S is the simulation's expected pool picks, the audience sizes are the
makers' and hunter's Product Hunt followers, the makers' and company X followers and pre-launch promotion reactions, the
conversion rates depend on track record (the makers' and hunter's past launches: the per-maker persistence E0 found) and page
scores, and browse is a base rate from page and day context. Two fits, rolling monthly (train on every earlier month, test the
next; tested May–Oct, 3,977 launches, 177 days):
- **glm**: the additive model, Poisson likelihood (torch, L-BFGS).
- **gbm**: monotone additive LightGBM (Poisson objective, each input in its own interaction group, non-decreasing in the pool and
  every audience size), 3 seeds.

Pool component: none, `psx_` (current person model), `psa_` (same, trained on every earlier month), `pna_` (no-page, all months:
what the daily pipeline deploys, from `deploy/20261102_pna`). Audience sizes are as fetched (undated), the same inputs the launch
model uses. X engagers are not in yet (about 64 launches covered); follower counts stand in. Scoring as the PH agent's
`lists_score.py` / `sim_src_score.py`: top-k on Product Hunt's real ranks, paired bootstrap over lists, 10,000 resamples.

## Daily top 3 / 5 / 10 (176 days for top 3/5, 144 for top 10)
| Model | Top 3 | Top 5 | Top 10 |
|---|---|---|---|
| **Launch model alone** (ctrl `all`) | **66.7** | **73.5** | **81.0** |
| E1 gbm, no pool | 55.1 | 67.2 | 76.2 |
| E1 gbm + `psx_` (current) | 58.0 | 67.6 | 76.3 |
| E1 gbm + `psa_` | 57.8 | 68.4 | 77.0 |
| E1 gbm + `pna_` (deployed) | 54.7 | 66.9 | 76.3 |
| E1 glm + `psx_` | 55.5 | 64.8 | 72.1 |
| E1 glm + `psa_` | 53.6 | 65.8 | 72.9 |
| E1 glm + `pna_` | 52.5 | 64.4 | 73.8 |

Paired differences (95% interval):
| Comparison | Top 3 | Top 5 | Top 10 |
|---|---|---|---|
| gbm + `psa_` − gbm + `psx_` | −0.2 [−2.5, +2.1] | +0.8 [−0.6, +2.3] | +0.7 [−0.1, +1.5] |
| gbm + `pna_` − gbm + `psx_` | −3.2 [−5.5, −0.9] | −0.7 [−2.0, +0.7] | −0.0 [−0.7, +0.7] |
| gbm + `psx_` − gbm, no pool | +2.8 [+0.4, +5.3] | +0.5 [−1.0, +1.9] | +0.1 [−0.8, +1.0] |
| gbm + `psa_` − launch model | −8.9 [−12.7, −5.3] | −5.1 [−7.6, −2.7] | −4.0 [−5.4, −2.5] |
| glm + `psa_` − glm + `psx_` | −1.9 [−4.5, +0.8] | +1.0 [−0.7, +2.7] | +0.8 [−0.4, +2.1] |

## Weekly top 3 / 5 / 10 (25 weeks; 23 for top 10)
| Model | Top 3 | Top 5 | Top 10 |
|---|---|---|---|
| Launch model alone | **49.3** | **56.0** | **58.3** |
| E1 gbm + `psx_` | 13.3 | 25.6 | 38.7 |
| E1 gbm + `psa_` | 18.7 | 25.6 | 42.2 |
| E1 gbm + `pna_` | 13.3 | 19.2 | 37.4 |

gbm + `psa_` − gbm + `psx_`: +5.3 [+0.0, +12.0] / +0.0 [−5.6, +5.6] / +3.5 [+0.4, +6.5]. Monthly (5–6 lists) is in
`vote_model_lists.txt`; it is anecdotal at that size.

## Total-vote log-likelihood (per launch, test; paired by day)
| Model | Log-likelihood | vs `psx_` |
|---|---|---|
| gbm, no pool | −18.30 | −0.91 [−1.46, −0.44] |
| gbm + `psx_` | −17.54 | |
| gbm + `psa_` | **−17.05** | **+0.39 [+0.10, +0.68]** |
| gbm + `pna_` | −17.81 | −0.31 [−0.70, +0.03] |

## Reading
- **The pool now counts in the vote model.** Adding the simulated pool to the audience model lifts daily top 3 by +2.8 [+0.4,
  +5.3] and the total-vote likelihood by 0.9 [0.4, 1.5]. In the launch-level GBM (`sim_src_score`) adding the simulation cost
  points; here it adds them.
- **`psa_` vs the current `psx_`:** better total-vote likelihood (+0.39 [+0.10, +0.68]) and weekly top 10 (+3.5 [+0.4, +6.5]);
  daily top 3/5/10 −0.2 / +0.8 / +0.7, all intervals spanning 0.
- **The deployed `pna_` (no page) is the weakest pool source here:** daily top 3 −3.2 [−5.5, −0.9] vs `psx_`. The page
  matters for the pool component.
- **E1 v1 is well below the launch model:** −8.9 daily top 3, and −30 on weekly. v1 has six audience inputs and a few
  conversion modifiers; the launch model has ~500 inputs. The weekly gap says the per-day level is poorly calibrated:
  ranking within a day survives, ranking across a week does not.
- **The additive glm is weaker than the monotone gbm** (55.5 vs 58.0 with `psx_`); the fitted rates are plausible (in
  October, 1.3–1.5 real votes per simulated pool pick, 0.17–0.29 votes per 1,000 maker PH followers, 0.19–0.27 per 1,000
  hunter followers, 0.02–0.05 per 1,000 X followers, a browse base of 80–120 votes).

## Next for E1
1. Calibrate the day level (the weekly gap): a day-level total-votes term (line-up size, weekday, the day's pool activity)
   and the launch model's other launch-level inputs as conversion modifiers, so E1 contains the launch model rather than
   competing with it.
2. Per-maker and per-hunter conversion learned from each one's past launches (residual persistence 0.25–0.44 from E0), with a
   prior from similar makers for first-timers.
3. X engagers as their own audience when coverage allows.
