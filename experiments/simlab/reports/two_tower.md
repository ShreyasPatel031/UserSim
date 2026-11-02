# E5: a trained person model (two-tower) against the hand-built one (Nov 2, 2026)

Question (direction review, E5): does a trained person model beat the hand-built LightGBM person model at predicting
which launches a Product Hunt person picks? Code: `experiments/simlab/two_tower.py`, branch `claude/person-model-v2`.
Compute: usersim-exp-1 (e2-standard-32, CPU only), shared with the PH agent's jobs.

## Setup (identical to pick_boost, the published baseline's harness)
- Same person, same day, same real line-up (~30 launches a day). Train on earlier months, test on the next, May–Oct.
- Test rows: pick_boost's own sample (200 people a day, seed 0): 36,531 person-days with at least one pick and one
  skip (May 6,168 / Jun 5,973 / Jul 6,179 / Aug 6,189 / Sep 5,994 / Oct 4,994, the same counts as `pick_ablate_tie2`).
- Everything dated before the day: histories, ties, collaborative filtering and category priors are cut at the month
  the baseline cuts them (training tables use priors fitted before their own month, test tables before the previous
  month, as pick_boost does).
- Scores, paired on the same rows: person-level top-3 hit, mean within-person-day AUC, and the pool-vote Spearman
  within day (expected picks summed over all of the day's active people, 14–22k person-days a month, against the real
  number of pool people who picked each launch; 178 days). 95% bootstrap intervals over person-days (top-3, AUC) and
  days (pool); per-month wins.

## Models
| Name | What |
|---|---|
| GBM prev | the baseline: LightGBM (400 trees, 31 leaves) on the hand features (popscore FEATS + page + taste + tie strength + TIE2 extensions), trained on the previous month, 300 people a day. This is `pick_ablate_tie2` base (55.8 / 0.728). |
| GBM all | the same model trained on every earlier month (Mar..m−1), 300 people a day each. |
| two-tower | PyTorch: person tower = the person's dated history before the day (newest 64 events; each event = the launch's encoding + kind + age bucket; attention pooling with a learned query, plus history size); launch tower = team member ids, topics, meaning embedding, page scores, weekday, line-up size; score = dot product + a bias MLP on the 17 tie-strength inputs. Loss = BCE + listwise softmax over the real line-up (every skipped launch is a negative). Trained on all earlier months (all active person-days, up to 117k), early stopping on a 10% hold-out of training person-days. |
| wide (run B) | two-tower whose bias MLP sees every hand feature of GBM all. |
| target attention (run C) | two-tower whose person tower also pools the history with the candidate launch as the query. |
| ensemble | mean of the two-tower's and GBM all's probabilities. |

## Results, May–Oct (run A: two-tower vs both GBMs)
| Model | Top-3 hit | AUC | Pool Spearman | Pool top-3 |
|---|---|---|---|---|
| GBM prev (baseline) | 55.9 | 0.728 | 0.565 | 55.2 |
| GBM all | **58.5** | **0.742** | **0.586** | **57.4** |
| two-tower | 52.8 | 0.709 | 0.508 | 51.7 |

Paired differences (95% interval; months better on top-3):
| Comparison | Top-3 | AUC | Pool Spearman | Pool top-3 | Months |
|---|---|---|---|---|---|
| two-tower − GBM prev | −3.1 [−3.6, −2.5] | −0.019 [−0.021, −0.016] | −0.057 [−0.086, −0.027] | −3.4 [−7.7, +0.8] | 1 of 6 (May +0.1) |
| two-tower − GBM all | −5.5 [−6.1, −5.1] | −0.033 [−0.035, −0.030] | −0.078 [−0.104, −0.049] | −5.6 [−9.4, −1.5] | 0 of 6 |
| GBM all − GBM prev | **+2.5 [+2.1, +2.9]** | **+0.014 [+0.012, +0.016]** | **+0.021 [+0.005, +0.037]** | +2.2 [−0.6, +4.9] | **6 of 6** |

Per month (top-3 hit / AUC / pool Spearman):
| Month | GBM prev | GBM all | two-tower |
|---|---|---|---|
| May | 51.6 / 0.742 / 0.546 | 53.5 / 0.757 / 0.574 | 51.7 / 0.737 / 0.541 |
| Jun | 54.4 / 0.707 / 0.592 | 56.0 / 0.714 / 0.619 | 50.6 / 0.681 / 0.502 |
| Jul | 55.1 / 0.686 / 0.522 | 58.4 / 0.711 / 0.568 | 51.5 / 0.676 / 0.520 |
| Aug | 61.0 / 0.736 / 0.605 | 64.0 / 0.754 / 0.627 | 56.3 / 0.718 / 0.508 |
| Sep | 57.9 / 0.739 / 0.552 | 59.2 / 0.743 / 0.544 | 55.3 / 0.711 / 0.475 |
| Oct | 55.6 / 0.759 / 0.574 | 59.6 / 0.772 / 0.581 | 51.4 / 0.733 / 0.500 |

- The baseline reproduces: 55.9 / 0.728 against the published 55.8 / 0.728.
- The pure two-tower loses to the baseline in 5 of 6 months and to GBM all in every month. Training loss keeps
  falling while the hold-out loss stalls after ~10 epochs (train 2.21 vs hold-out 2.33 in Oct): it fits the training
  months and does not carry over, where the hand features (ties counted by maker and hunter, recency, within-line-up
  standing, category priors, collaborative filtering) carry over directly.
- Training is cheap: 15–60 s an epoch on 2–4 cores, 4–16 min a month. Many variants can be run.

## The gain that is real: train the hand model on more months
GBM all is the same hand model trained on every earlier month instead of the previous one: top-3 58.5 vs 55.9,
+2.5 [+2.1, +2.9], better in 6 of 6 months (+1.3 to +4.0), with the pool-vote Spearman also up (+0.021 [+0.005,
+0.037]). This is a one-line change in `popscore.train_month` (train on Mar..m−1, 300 people a day each) and lifts
`psr_`/`pnx_` for E1 directly.

## Runs B and C
(pending)
