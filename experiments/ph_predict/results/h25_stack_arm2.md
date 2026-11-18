# 2025 decomposition and stacking (214 days Apr-Oct; 5 seeds; share of launches whose hunter has 2025 history 38.5%)

## (a) model alone

| arm | top 3 | top 5 | top 10 | daily rho | seed sd t3 | diff vs pure (t3 / t5 / t10 / rho, 95%) |
|---|---|---|---|---|---|---|
| pure | 56.9 | 67.6 | 75.0 | 0.613 | 0.6 | - |
| histonly | 56.4 | 68.5 | 74.5 | 0.616 | 0.4 | -0.5 [-2.5, +1.6] / +0.9 [-0.5, +2.2] / -0.4 [-1.0, +0.2] / +0.003 [-0.005, +0.011] |
| rowsonly | 58.9 | 68.1 | 75.2 | 0.632 | 0.4 | +2.0 [-0.3, +4.4] / +0.6 [-0.9, +2.1] / +0.3 [-0.4, +1.0] / +0.018 [+0.004, +0.033] |
| both | 60.7 | 68.4 | 75.7 | 0.642 | 0.9 | +3.9 [+1.6, +6.5] / +0.8 [-0.8, +2.5] / +0.7 [+0.0, +1.5] / +0.028 [+0.013, +0.045] |

## (b) both - pure, by whether the hunter has 2025 history (top 3 / 5 / 10 hits counted on launches of that group only is not defined per day; reported: mean rank-percentile gain of the true top-3 launches)

- hunter has 2025 history = False: final top-3 launches n 106, mean within-day percentile gain +0.019 [-0.005, +0.044]
- hunter has 2025 history = True: final top-3 launches n 534, mean within-day percentile gain +0.011 [+0.004, +0.018]

## (c) stacking with th_n_pre (LODO ridge)

| model | top 3 | top 5 | top 10 | diff vs clean_nosite + th_n_pre (95%) |
|---|---|---|---|---|
| clean_nosite (tw_nosite) + th_n_pre | 60.1 | 68.7 | 75.3 | - |
| pure + th_n_pre | 60.1 | 68.5 | 75.2 | -0.0 [-1.2, +1.1] / -0.2 [-0.9, +0.6] / -0.0 [-0.5, +0.3] |
| histonly + th_n_pre | 59.7 | 69.6 | 75.1 | -0.5 [-2.2, +1.2] / +0.9 [-0.3, +2.1] / -0.2 [-0.7, +0.4] |
| rowsonly + th_n_pre | 60.4 | 69.2 | 75.4 | +0.3 [-1.7, +2.3] / +0.5 [-0.9, +1.9] / +0.1 [-0.6, +0.9] |
| both + th_n_pre | 61.4 | 69.4 | 75.7 | +1.2 [-0.8, +3.4] / +0.7 [-0.8, +2.2] / +0.5 [-0.3, +1.2] |
| pure tie-break (pos 2-6 by z(pure) + z(th_n_pre)) | 59.8 | 67.5 | 75.0 | -0.3 [-1.9, +1.2] / -1.2 [-2.4, -0.1] / -0.3 [-0.9, +0.3] |
| both tie-break (pos 2-6 by z(both) + z(th_n_pre)) | 60.9 | 68.8 | 75.7 | +0.8 [-1.2, +2.8] / +0.1 [-1.6, +1.7] / +0.4 [-0.4, +1.3] |
