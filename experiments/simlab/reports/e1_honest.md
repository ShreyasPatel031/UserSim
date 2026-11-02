# Honest E1 retrain against the day-only control (Nov 2, 2026; Shreyas approved)

Code: `simlab/e1_honest.py`; data `reports/e1_honest.json`. Every input is honest pre-launch:
- **Offset:** the honest launch model (`ph_predict/honest.py`, `honest` column: no follower counts, no follow lists, no
  undated promotion fields), PH ops' file from the bucket. My independent rebuild with the same code matched it exactly
  (5,564 launches, correlation 1.0, mean difference 0.0).
- **Inputs:** the page-free pool simulation (`pna_` expected picks); dated pre-launch promotion (promo_posts, _launch,
  _li, _x, _founder; promo_cov, _press, _hn, _reddit); track record (8 hist_ inputs); page (99 ps_ / vs_ / pf_ inputs);
  day terms. No follower count of any kind.
- **Control:** the honest offset + day terms (the honest launch model calibrated per day).
- Poisson LightGBM, rolling monthly, May–Oct (3,977 launches, 176 days for daily top 3/5, 144 for top 10, 25 weeks),
  5 seeds averaged, non-decreasing in the pool and the promotion counts. Paired by day / week, 10,000 resamples.
- **Decision rule fixed before the run:** a variant adds daily value if daily top 3 against the control has a 95%
  interval above 0.

| Model | Daily top 3 / 5 / 10 | Weekly top 3 / 5 / 10 | Log-lik / launch |
|---|---|---|---|
| Honest launch model alone | 64.4 / 70.5 / 76.9 | 45.3 / 54.4 / 55.7 | −14.132 |
| **Control (day-calibrated)** | **64.4 / 70.5 / 76.9** | **50.7 / 56.0 / 54.8** | −13.900 |
| + pool | 63.1 / 70.6 / 77.2 | 53.3 / 56.8 / 56.1 | **−13.788** |
| + promotion | 64.2 / 69.8 / 77.0 | 46.7 / 54.4 / 54.8 | −13.991 |
| + pool + promotion + track record | 63.6 / 69.9 / 77.0 | 46.7 / 51.2 / 55.7 | −14.056 |
| + everything honest | 62.7 / 69.8 / 76.7 | 46.7 / 53.6 / 56.1 | −13.843 |

Control − honest launch model: weekly top 3 **+5.3 [+1.3, +10.7]**, top 5 +1.6 [−1.6, +4.8], top 10 −0.9 [−2.6, +0.9];
log-likelihood **+0.38 [+0.10, +0.68]**; daily identical by construction.

| Paired against the control | Daily top 3 | Top 5 | Top 10 | Weekly top 3 | Weekly top 5 | Log-lik | Months better / tied / worse |
|---|---|---|---|---|---|---|---|
| + pool | −1.3 [−2.7, +0.0] | +0.1 [−0.7, +0.9] | +0.3 [−0.3, +0.8] | +2.7 [+0.0, +6.7] | +0.8 [−1.6, +3.2] | +0.01 [−0.19, +0.20] | 0 / 2 / 4 |
| + promotion | −0.2 [−1.7, +1.1] | −0.7 [−1.6, +0.2] | +0.1 [−0.6, +0.9] | −4.0 [−8.0, +0.0] | −1.6 [−4.0, +0.0] | −0.10 [−0.23, +0.03] | 3 / 0 / 3 |
| + pool + promotion + track record | −0.8 [−3.0, +1.5] | −0.6 [−1.6, +0.5] | +0.1 [−0.6, +0.9] | −4.0 [−9.3, +0.0] | −4.8 [−9.6, −0.0] | **−0.48 [−0.86, −0.12]** | 1 / 2 / 3 |
| + everything honest | −1.7 [−4.0, +0.6] | −0.7 [−1.9, +0.6] | −0.1 [−1.0, +0.7] | −4.0 [−10.7, +0.0] | −2.4 [−6.4, +1.6] | −0.31 [−0.64, +0.03] | 0 / 1 / 5 |

## Verdict
- **No honest input adds daily value over the day-calibrated launch model.** Every variant fails the rule; the point
  estimates on daily top 3 are all at or below 0 (−0.2 to −1.7), and the pool alone is worse in 4 of 6 months and
  never better.
- **The pool's only effect is a small weekly top-3 gain** (+2.7 [+0.0, +6.7]) with no change in the vote likelihood.
- Adding track record and page inputs again (the launch model already has them) overfits: log-likelihood −0.48.
- **Day-level calibration is the one honest gain:** weekly top 3 +5.3 [+1.3, +10.7] and log-likelihood +0.38 over the
  honest launch model. That is `shadow_daycal`, already in PH ops' bundle.
- With the leaky inputs removed, the earlier E1 v1/v2 gains do not survive; this agrees with PH ops' rebuild
  (daily −1.3 / −0.3 / −0.3).

## What it means for the next test
Pre-launch, the honest inputs we have, including every aggregate of the simulated pool, do not reorder launches within
a day beyond the launch model. A daily gain needs new pre-launch information about each launch's launch-day shock:
at-launch follower counts (collected since Oct 25; a retrain once 3–4 weeks exist), pre-launch X engagement as coverage
grows, and the makers' own outreach.
