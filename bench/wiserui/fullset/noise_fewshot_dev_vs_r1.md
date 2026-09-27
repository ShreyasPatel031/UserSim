n = 75 pairs

| arm | CA [95% CI] | dCA vs base [95% CI] | McNemar p (n01/n10) | significant | AA | FA / SA | OI [95% CI] | dOI [95% CI] | $/pair |
|---|---|---|---|---|---|---|---|---|---|
| base_t0_r1 | 53.3 [42.7, 64.0] | (baseline) | (baseline) | (baseline) | 68.0 | 61.3 / 74.7 | 68.0 [59.3, 76.7] | (baseline) | 0.0112 |
| fewshot_k3 | 50.7 [40.0, 61.3] | -2.7 [-8.0, +2.7] | 0.625 (1/3) | no | 64.7 | 58.7 / 70.7 | 64.7 [55.3, 73.3] | -3.3 [-6.7, +0.0] | 0.0120 |
| fewshot_k5 | 46.7 [36.0, 57.3] | -6.7 [-13.3, -1.3] | 0.062 (0/5) | no | 62.0 | 57.3 / 66.7 | 62.0 [52.7, 70.7] | -6.0 [-11.3, -1.3] | 0.0127 |

n01 = pairs the baseline got wrong (CA) and the arm right; n10 = the reverse. Significant = McNemar p < 0.05 and the bootstrap CI of dCA excludes 0.
