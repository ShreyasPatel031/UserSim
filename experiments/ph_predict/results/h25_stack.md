# 2025 decomposition and stacking (214 days Apr-Oct; 5 seeds; share of launches whose hunter has 2025 history 33.3%)

## (a) model alone

| arm | top 3 | top 5 | top 10 | daily rho | seed sd t3 | diff vs pure (t3 / t5 / t10 / rho, 95%) |
|---|---|---|---|---|---|---|
| pure | 56.9 | 67.6 | 75.0 | 0.613 | 0.6 | - |
| histonly | 55.3 | 67.2 | 74.7 | 0.617 | 0.4 | -1.6 [-3.6, +0.5] / -0.4 [-1.5, +0.7] / -0.3 [-0.8, +0.3] / +0.003 [-0.005, +0.012] |
| rowsonly | 57.0 | 67.1 | 75.5 | 0.626 | 0.3 | +0.2 [-2.0, +2.2] / -0.5 [-1.7, +0.8] / +0.6 [-0.1, +1.3] / +0.012 [+0.001, +0.025] |
| both | 57.8 | 68.1 | 75.4 | 0.630 | 0.8 | +0.9 [-1.2, +3.3] / +0.6 [-0.8, +2.0] / +0.5 [-0.3, +1.2] / +0.016 [+0.005, +0.028] |

## (b) both - pure, by whether the hunter has 2025 history (top 3 / 5 / 10 hits counted on launches of that group only is not defined per day; reported: mean rank-percentile gain of the true top-3 launches)

- hunter has 2025 history = False: final top-3 launches n 148, mean within-day percentile gain -0.001 [-0.018, +0.017]
- hunter has 2025 history = True: final top-3 launches n 492, mean within-day percentile gain +0.005 [-0.002, +0.013]

## (c) stacking with th_n_pre (LODO ridge)

| model | top 3 | top 5 | top 10 | diff vs clean_nosite + th_n_pre (95%) |
|---|---|---|---|---|
| clean_nosite (tw_nosite) + th_n_pre | 60.1 | 68.7 | 75.3 | - |
| pure + th_n_pre | 60.1 | 68.5 | 75.2 | -0.0 [-1.2, +1.1] / -0.2 [-0.9, +0.6] / -0.0 [-0.5, +0.3] |
| histonly + th_n_pre | 59.7 | 68.9 | 75.0 | -0.5 [-2.3, +1.4] / +0.2 [-0.8, +1.3] / -0.3 [-0.8, +0.2] |
| rowsonly + th_n_pre | 59.3 | 69.1 | 75.2 | -0.8 [-2.8, +1.3] / +0.4 [-0.7, +1.5] / -0.0 [-0.7, +0.7] |
| both + th_n_pre | 60.6 | 70.3 | 75.3 | +0.5 [-1.6, +2.5] / +1.6 [+0.4, +2.8] / +0.0 [-0.7, +0.7] |
| pure tie-break (pos 2-6 by z(pure) + z(th_n_pre)) | 59.8 | 67.5 | 75.0 | -0.3 [-1.9, +1.2] / -1.2 [-2.4, -0.1] / -0.3 [-0.9, +0.3] |
| both tie-break (pos 2-6 by z(both) + z(th_n_pre)) | 60.3 | 69.0 | 75.4 | +0.2 [-1.9, +2.3] / +0.3 [-1.1, +1.6] / +0.1 [-0.7, +1.0] |
