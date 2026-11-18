# 2025 decomposition and stacking (214 days Apr-Oct; 5 seeds; share of launches whose hunter has 2025 history 38.5%)

## (a) model alone

| arm | top 3 | top 5 | top 10 | daily rho | seed sd t3 | diff vs pure (t3 / t5 / t10 / rho, 95%) |
|---|---|---|---|---|---|---|
| pure | 56.9 | 67.6 | 75.0 | 0.613 | 0.6 | - |
| histonly | 56.4 | 68.5 | 74.5 | 0.616 | 0.4 | -0.5 [-2.5, +1.6] / +0.9 [-0.5, +2.2] / -0.4 [-1.0, +0.2] / +0.003 [-0.005, +0.011] |
| rowsonly | 58.6 | 67.7 | 75.2 | 0.625 | 0.7 | +1.7 [-0.6, +4.0] / +0.1 [-1.3, +1.6] / +0.3 [-0.5, +1.0] / +0.012 [-0.002, +0.027] |
| both | 58.7 | 67.9 | 75.1 | 0.632 | 0.7 | +1.9 [-0.6, +4.7] / +0.3 [-1.4, +2.0] / +0.1 [-0.6, +0.9] / +0.019 [+0.005, +0.034] |

## (b) both - pure, by whether the hunter has 2025 history (top 3 / 5 / 10 hits counted on launches of that group only is not defined per day; reported: mean rank-percentile gain of the true top-3 launches)

- hunter has 2025 history = False: final top-3 launches n 106, mean within-day percentile gain +0.006 [-0.016, +0.027]
- hunter has 2025 history = True: final top-3 launches n 534, mean within-day percentile gain +0.008 [+0.000, +0.015]

## (c) stacking with th_n_pre (LODO ridge)

| model | top 3 | top 5 | top 10 | diff vs clean_nosite + th_n_pre (95%) |
|---|---|---|---|---|
| clean_nosite (tw_nosite) + th_n_pre | 60.1 | 68.7 | 75.3 | - |
| pure + th_n_pre | 60.1 | 68.5 | 75.2 | -0.0 [-1.2, +1.1] / -0.2 [-0.9, +0.6] / -0.0 [-0.5, +0.3] |
| histonly + th_n_pre | 59.7 | 69.6 | 75.1 | -0.5 [-2.2, +1.2] / +0.9 [-0.3, +2.1] / -0.2 [-0.7, +0.4] |
| rowsonly + th_n_pre | 60.6 | 68.7 | 75.2 | +0.5 [-1.7, +2.6] / +0.0 [-1.2, +1.3] / -0.1 [-0.7, +0.6] |
| both + th_n_pre | 60.3 | 69.1 | 75.2 | +0.2 [-2.0, +2.3] / +0.4 [-1.1, +1.8] / -0.0 [-0.8, +0.7] |
| pure tie-break (pos 2-6 by z(pure) + z(th_n_pre)) | 59.8 | 67.5 | 75.0 | -0.3 [-1.9, +1.2] / -1.2 [-2.4, -0.1] / -0.3 [-0.9, +0.3] |
| both tie-break (pos 2-6 by z(both) + z(th_n_pre)) | 60.0 | 67.9 | 75.1 | -0.2 [-2.6, +2.3] / -0.7 [-2.3, +0.8] / -0.2 [-1.1, +0.7] |
