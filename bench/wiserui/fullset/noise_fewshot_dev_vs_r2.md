n = 75 pairs

| arm | CA [95% CI] | dCA vs base [95% CI] | McNemar p (n01/n10) | significant | AA | FA / SA | OI [95% CI] | dOI [95% CI] | $/pair |
|---|---|---|---|---|---|---|---|---|---|
| base_t0_r2 | 52.0 [41.3, 62.7] | (baseline) | (baseline) | (baseline) | 66.7 | 64.0 / 69.3 | 66.7 [58.0, 75.3] | (baseline) | 0.0112 |
| fewshot_k3 | 50.7 [40.0, 61.3] | -1.3 [-5.3, +2.7] | 1.000 (1/2) | no | 64.7 | 58.7 / 70.7 | 64.7 [55.3, 73.3] | -2.0 [-5.3, +1.3] | 0.0120 |
| fewshot_k5 | 46.7 [36.0, 57.3] | -5.3 [-10.7, -1.3] | 0.125 (0/4) | no | 62.0 | 57.3 / 66.7 | 62.0 [52.7, 70.7] | -4.7 [-9.3, +0.0] | 0.0127 |

n01 = pairs the baseline got wrong (CA) and the arm right; n10 = the reverse. Significant = McNemar p < 0.05 and the bootstrap CI of dCA excludes 0.
