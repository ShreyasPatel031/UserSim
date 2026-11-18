# Pre-launch comment votes (live feed, reads <= 01:00 PT; 2 days 2026-11-04..2026-11-08; 51 ranked launches; THIN)

Launches with any pre-launch non-hunter comment read: 35; residual Spearman vs base (in-sample): pcv_sum +0.16, pcv_max +0.15, pcv_n2 -0.19

| variant | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |
|---|---|---|---|---|---|---|
| clean_nosite + th_n_pre | 83.3 | 70.0 | 75.0 | - | - | - |
| + pcv_sum | 66.7 | 70.0 | 80.0 | -16.7 [-33.3, +0.0] | +0.0 [+0.0, +0.0] | +5.0 [+0.0, +10.0] |
| + pcv_max | 66.7 | 70.0 | 75.0 | -16.7 [-33.3, +0.0] | +0.0 [+0.0, +0.0] | +0.0 [+0.0, +0.0] |
| + pcv_n2 | 83.3 | 70.0 | 75.0 | +0.0 [+0.0, +0.0] | +0.0 [+0.0, +0.0] | +0.0 [+0.0, +0.0] |
| + all three | 50.0 | 60.0 | 80.0 | -33.3 [-33.3, -33.3] | -10.0 [-20.0, +0.0] | +5.0 [+0.0, +10.0] |

Frozen weights -> results/frozen/clean_nosite_pcv_20261113.json
