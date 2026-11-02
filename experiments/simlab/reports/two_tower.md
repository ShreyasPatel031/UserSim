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

## Runs B and C: richer two-towers, and the ensemble
Pooled over May–Oct (top-3 / AUC / pool Spearman / pool top-3):
| Model | Run | Result |
|---|---|---|
| wide two-tower (every hand feature in the head) | B | 52.3 / 0.709 / 0.490 / 48.0 |
| target-attention two-tower | C | 53.9 / 0.713 / 0.502 / 50.6 |
| ensemble: wide + GBM all | B | 57.8 / 0.742 / 0.582 / 55.1 |
| **ensemble: target attention + GBM all** | C | **59.0 / 0.745 / 0.586 / 58.4** |

Paired differences (95% interval; months better on top-3):
| Comparison | Top-3 | AUC | Pool Spearman | Pool top-3 | Months |
|---|---|---|---|---|---|
| wide − GBM prev | −3.6 [−4.1, −3.0] | −0.018 [−0.021, −0.016] | −0.074 [−0.107, −0.040] | −7.1 [−10.9, −3.4] | 0 of 6 |
| target attention − GBM prev | −2.1 [−2.6, −1.5] | −0.015 [−0.018, −0.012] | −0.063 [−0.094, −0.032] | −4.7 [−8.6, −0.9] | 1 of 6 |
| ensemble (C) − GBM prev | **+3.0 [+2.6, +3.5]** | **+0.017 [+0.015, +0.019]** | +0.021 [−0.001, +0.044] | +3.2 [−0.0, +6.6] | **6 of 6** |
| ensemble (C) − GBM all | **+0.6 [+0.2, +0.9]** | **+0.003 [+0.001, +0.004]** | +0.001 [−0.018, +0.021] | +0.9 [−2.2, +4.1] | 4 of 6 |
| ensemble (B) − GBM all | −0.6 [−0.9, −0.2] | −0.000 [−0.002, +0.001] | −0.003 [−0.024, +0.019] | −2.2 [−5.1, +0.6] | 2 of 6 |

Per month, ensemble (C) vs GBM all, top-3: May 56.2 vs 53.5, Jun 56.4 vs 56.0, Jul 58.1 vs 58.4, Aug 62.6 vs 64.0,
Sep 60.7 vs 59.2, Oct 60.1 vs 59.6.

- Target attention (pooling the history with the candidate launch as the query) is the best net: +1.1 top-3 over the
  plain two-tower (53.9 vs 52.8). Feeding every hand feature to the head (wide) makes the net worse (52.3): it learns
  the hand signal less well than LightGBM does and crowds out the history towers.
- The net is wrong in different places from the hand model: averaging the two beats either alone. The ensemble is the
  best person model measured so far: 59.0 / 0.745, against the published 55.8 / 0.728.
- At pool level (votes summed over the day's people) the net adds nothing beyond GBM all: +0.001 [−0.018, +0.021].

## Launch level: the pool sum (`psv_`, `psg_`)
Each day's 30-day population (everyone active in the 30 days before, weighted by share of days active; 30–140k
person-launch rows a day) scored by each month's models, summed per launch exactly as popscore phase B. Every model is
trained only on months before the scored month. 177 days, 4,149 launches; 150 days have a complete real top 10.
Simulation-only: launches ranked by the pool sum alone, no reach inputs (the launch model is the PH agent's, E1).

| Pool sum from | Pool-vote Spearman | Pool top-3 | Daily top 3 | Top 5 | Top 10 |
|---|---|---|---|---|---|
| `psg_`: GBM all | **0.587** | **56.4** | **55.4** | **63.7** | **73.5** |
| `psv_`: ensemble (C) | 0.578 | 55.8 | 55.0 | 61.4 | 73.1 |
| net alone (C) | 0.490 | 47.1 | 46.4 | 54.0 | 67.8 |

Paired against `psg_` over days (95% interval):
| | Spearman | Pool top-3 | Top 3 | Top 5 | Top 10 |
|---|---|---|---|---|---|
| ensemble − GBM all | −0.008 [−0.024, +0.007] | −0.7 [−4.0, +2.7] | −0.4 [−3.8, +2.9] | −2.3 [−4.5, −0.1] | −0.4 [−1.9, +1.1] |
| net − GBM all | −0.097 [−0.123, −0.070] | −9.3 [−13.6, −5.1] | −9.0 [−13.5, −4.3] | −9.7 [−13.0, −6.4] | −5.7 [−7.7, −3.7] |

- The net's small person-level edge does not survive summing over the pool: the ensemble ties GBM all on pool votes
  and loses 2.3 on top 5. The person-level test samples active people evenly; the pool sum is dominated by heavy,
  well-tied people, where the hand ties already carry the signal.
- `psg_` is the stronger launch-level input. Its pool-vote Spearman (0.587) is comparable in definition to the
  log's 0.488 for `pnx_` (pool_check: Spearman of the summed expected picks with the pool's real votes, within day),
  but on a different configuration (pnx has no page inputs, psg has page, taste and TIE2) and a slightly different
  day filter (here at least 10 launches); the like-for-like comparison against the `psr_`/`psx_` day files is for the
  PH agent, who has them.
- Files (launch id → `_ev, _fans, _ev_ties, _reach, _pmax, _share, _top1, _top3`, the `psr_features.json` format):
  `gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/features/psg_features.json`, `.../psv_features.json`, and the
  per-launch day rows `.../pop_att_ens.parquet`. Written by `two_tower features` with `ENS=1 ATT=1 TAG=_att`.

## Verdict
- **Person level: the trained model beats the hand-built one only as a partner.** Alone, every two-tower variant
  loses to the published baseline (−2.1 to −3.6 top-3). Averaged with the hand model, it beats the published baseline
  by +3.0 [+2.6, +3.5] in 6 of 6 months, and the all-months hand model by +0.6 [+0.2, +0.9].
- **Most of the gain is training the hand model on more months** (+2.5 [+2.1, +2.9] of the +3.0), which needs no
  neural model. It also lifts the pool-vote Spearman (+0.021 [+0.005, +0.037] at person-day level).
- **Launch level: the net adds nothing.** Summed over the pool, the ensemble ties the all-months hand model on pool
  votes and daily top 3/10, and loses on top 5 (−2.3 [−4.5, −0.1]). `psg_` (all-months hand model) is the input to
  test in the generative vote model (E1) on daily top 3/5/10; `psv_` is there for completeness.

## Next levers for the trained model
1. Regularisation (the hold-out loss stalls while the training loss falls): dropout, weight decay, a lower learning
   rate, a smaller dimension, listwise-only loss. Not run: the net's gain does not survive the pool sum, so tuning it
   alone will not move the leaderboard (orchestrator's call, Nov 2).
2. Several seeds averaged: ensembling helped once already, and seeds are free.
3. Train the net on the residual of GBM all (boosting the hand model), not on its own: the net only has to learn what
   the hand model misses.
4. Weight training toward the people who carry the pool sum (heavy, well-tied people), since that is where the
   launch-level score is decided; the person-level test weights every active person-day equally.

## Engineering notes
- Fork-safety: a pool forked after LightGBM or torch has run in the parent deadlocks in OpenMP (py-spy: stuck in
  `load_state_dict`). `two_tower features` fits per-month models in a separate `prep` process and uses spawned
  workers that load their own state.
- Waiters that `pgrep -f` for a pattern their own command line contains never fire; put waiters in a script file.
