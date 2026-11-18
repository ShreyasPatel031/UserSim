# Top 5 / top 10 anatomy, arm 2 (214 days Apr-Oct 2026)

Launches: misses 392, false picks 426, hits 1004.

Mean per-input points (readable v2, log-vote scale) and th_n_pre by group; last columns: miss - hit and false pick - hit.

| input | A miss | B false pick | H hit | A - H | B - H |
|---|---|---|---|---|---|
| th_n_pre | 0.149 | 0.281 | 0.455 | -0.307 | -0.174 |
| hist_hunter_rel | -0.045 | 0.037 | 0.073 | -0.118 | -0.036 |
| hist_hunter_top5 | -0.039 | 0.018 | 0.052 | -0.091 | -0.034 |
| ph_n_makers | -0.029 | 0.041 | 0.048 | -0.077 | -0.008 |
| llm_pitch | -0.016 | 0.031 | 0.041 | -0.057 | -0.010 |
| ph_hunter_age_d | -0.010 | 0.025 | 0.025 | -0.035 | -0.001 |
| txt_ridge | -0.005 | 0.015 | 0.017 | -0.022 | -0.001 |
| hist_hunter_n | 0.001 | 0.016 | 0.023 | -0.022 | -0.007 |
| topic_prior_mean | -0.010 | 0.015 | 0.010 | -0.020 | +0.005 |
| promo_cov | -0.036 | -0.027 | -0.030 | -0.006 | +0.003 |
| ph_n_media | 0.004 | 0.005 | 0.004 | -0.000 | +0.001 |

Model rank of misses: 11-15 60%, 16-20 21%, >20 19% (median 14).

## Oracle headroom

- Top 10: model 75.7; if every true top-10 launch the model had at 11-15 swapped in for a false pick at 6-10: 86.1 (+10.4).
- Top 5: model 68.4; swapping true top-5 launches at model 6-8 in for false picks at 4-5: 82.1 (+13.6).
