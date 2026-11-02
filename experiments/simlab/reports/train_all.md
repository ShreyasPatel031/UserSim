# Person model trained on every earlier month (popscore TRAIN_ALL, `psa_`), Nov 2, 2026

> **Leakage note (Nov 2, 12:30 UTC, from PH ops):** in the backtest, all follower counts (PH and X, with their day ranks
> and ctx_ derivatives), fol_* / seg_*, and several promo_ fields (promo_reactions, promo_founder_li, promo_company_li,
> promo_founder_x, promo_funding, promo_company_age, promo_n_sources) were read after launch day and partly encode the
> outcome. The launch model's backtest predictions (ctrl `all`, the offset used here) include them, and E1 v2's "live"
> audiences include four of them (ph_hunter_followers, x_maker_sum_followers, x_company_followers, promo_reactions).
> Absolute levels here are therefore optimistic. PH ops' rebuild on the honest offset (results/honest_preds.parquet,
> `honest`; model.py honest_drop(), commit adf5e98 on claude/ph-ops-agent) with promo_posts as the only audience gives
> daily top 3/5/10 −1.3 / −0.3 / −0.3 and weekly gains no larger than the day-terms-only control. The E1 v2 shadow package
> was trained on the leaky backtest values; its live inputs are at-launch counts, so its live scores will not match this
> backtest. Honest inputs: promo_posts*, promo_cov*, hist_*, the pool (pna_), page and day inputs; at-launch follower counts
> once 3–4 weeks of them exist.

Change: `popscore.train_month` with `TRAIN_ALL=1` trains each month's person model on every earlier month from March
instead of only the previous month. Each month's rows are built exactly as the previous-month model's are (up to 300
active people a day, seed 0, collaborative filtering and category priors cut at that month's start). The LightGBM
settings are unchanged (300 trees, 15 leaves), so only the training window differs. Configuration TASTE=1 TIE2=1,
the current page-aware person model: `psx_` (previous month) against `psa_` (all earlier months).
Run on usersim-exp-2 with the PH agent's current code and data (copied from usersim-exp-1, Nov 2 08:06 UTC).
Every model is trained only on months before the month it scores. All comparisons are paired by day on identical
launches, 95% bootstrap intervals over days.

## 1. Launch model (`ph_predict/sim_src_score.py`, the PH agent's script, unchanged)
LightGBM on final log votes from the launch model's prediction plus the source's simulation inputs and their
within-day standing; rolling monthly, 3 seeds; 4,876 launches, Apr–Oct, tested May–Oct (176 days for top 3/5,
144 for top 10).

| | Daily top 3 | Top 5 | Top 10 |
|---|---|---|---|
| Launch model alone | **66.7** | **73.5** | **81.0** |
| Launch model + `psx_` (current) | 65.0 | 73.3 | 79.2 |
| Launch model + `psa_` (all months) | 65.3 | 73.1 | 80.1 |

| Paired difference | Top 3 | Top 5 | Top 10 |
|---|---|---|---|
| + `psa_` − + `psx_` | +0.4 [−2.5, +3.2] | −0.2 [−2.0, +1.6] | +0.8 [−0.0, +1.7] |
| + `psa_` − launch model alone | −1.3 [−3.8, +1.3] | −0.5 [−2.2, +1.2] | −0.9 [−1.7, −0.1] |
| + `psx_` − launch model alone | −1.7 [−4.5, +1.1] | −0.2 [−1.7, +1.2] | −1.7 [−2.7, −0.7] |

## 2. Simulation-only forecast (`newsim_eval.py STAGE=2 STAGE3=1`, page configuration)
2,540 launches, tested Jul–Oct (116 days for top 3/5, 101 for top 10); `ph_predict/paired_launch.py`.

| Configuration | `psx_` | `psa_` | Top 3 change | Top 5 change | Top 10 change |
|---|---|---|---|---|---|
| sim + reach + audience | 59.5 / 69.1 / 79.5 | 61.5 / 70.0 / 80.3 | +2.0 [−1.1, +5.2] | +0.9 [−1.2, +3.1] | +0.8 [−0.2, +1.8] |
| + day standing | 60.6 / 69.3 / 80.4 | 59.8 / 70.0 / 80.3 | −0.9 [−3.4, +1.7] | +0.7 [−0.9, +2.2] | −0.1 [−1.0, +0.8] |
| + page | 61.8 / 69.7 / 79.9 | 61.8 / 71.0 / 80.7 | −0.0 [−2.9, +2.9] | +1.4 [−0.5, +3.3] | +0.8 [−0.3, +1.9] |
| + day standing + page (best) | 62.1 / 70.7 / 80.0 | 62.9 / 70.7 / 80.2 | +0.9 [−1.4, +3.2] | +0.0 [−1.7, +1.7] | +0.2 [−0.4, +0.8] |
| launch model alone (same days) | 65.8 / 73.1 / 81.3 | | | | |

The `psx_` numbers differ slightly from the Nov 1 log (61.5 / 70.5 / 80.2) because the launch model's saved
predictions were rebuilt on Nov 2 at 04:28 UTC; both sources here use the same current inputs.

## 3. Pool check (the pool's own votes, 207 days)
| | Spearman (ev) | Pool top 3 (ev) |
|---|---|---|
| `psx_` | 0.535 | 52.8 |
| `psa_` | 0.551 | 56.0 |
| `psa_` − `psx_` | **+0.016 [+0.001, +0.032]** | **+3.2 [+0.6, +5.8]** |

## Verdict
- **At the pool level, training on every earlier month helps:** the simulated pool's votes match the real pool's
  better (+3.2 [+0.6, +5.8] on the pool's top 3), as at person level (+2.5 top-3 hit in E5).
- **It does not move the leaderboard numbers.** On the launch model, adding `psa_` instead of `psx_` changes daily
  top 3/5/10 by +0.4 / −0.2 / +0.8, every interval spanning 0. In the best simulation-only configuration the change
  is +0.9 / 0.0 / +0.2, also within noise.
- **Neither simulation source improves the launch model:** the launch model alone stays best (66.7 / 73.5 / 81.0);
  adding `psa_` costs −1.3 / −0.5 / −0.9 (top 10 interval excludes 0), adding `psx_` −1.7 / −0.2 / −1.7.
- The pool is about 31% of votes and the launch model already carries reach; a better pool sum does not reach the
  leaderboard through this launch-level GBM. That is the case for the generative vote model (E1), where the pool
  component is an additive count rather than one more input to a model that leans on reach.
- `TRAIN_ALL=1` is safe to adopt for the simulation (better pool votes, no loss at launch level).

Files: `reports/sim_src_score_psx_psa.json`, `reports/paired_psx_psa_stage3.json`; features
`ph_predict/data/psa_features.json` (copy in `gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/features/`).
