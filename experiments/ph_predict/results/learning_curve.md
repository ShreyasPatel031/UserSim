# Arm 2 learning curve over history length (214 days Apr-Oct 2026, month walk-forward, 5 seeds)

| training days (most recent N) | top 3 / 5 / 10 | rho | diff vs all history, t3 / t5 / t10 (95%) |
|---|---|---|---|
| 150 | 56.2 / 67.3 / 74.3 | 0.614 | -4.5 [-6.9, -2.3] / -1.1 [-2.7, +0.5] / -1.4 [-2.1, -0.6] |
| 250 | 56.7 / 67.5 / 75.1 | 0.626 | -4.0 [-6.2, -1.9] / -0.9 [-2.5, +0.5] / -0.6 [-1.3, +0.1] |
| 350 | 58.9 / 68.0 / 75.3 | 0.632 | -1.9 [-3.4, -0.2] / -0.4 [-1.5, +0.7] / -0.4 [-1.0, +0.2] |
| 450 | 60.0 / 68.6 / 75.2 | 0.640 | -0.8 [-2.2, +0.6] / +0.2 [-0.7, +1.1] / -0.5 [-1.0, +0.0] |
| all (~546) | 60.7 / 68.4 / 75.7 | 0.642 | - |

Fit top 3 = +3.73 x ln(training days) +37.0 (per doubling +2.59 points; slope 95% [+1.32, +3.84] per doubling).
Extrapolated top 3 at 1,000 days (adding 2024): 62.8 [59.2, 66.2]; at 1,400 days (adding 2023): 64.0 [60.1, 67.8] (day-bootstrap interval of the fitted line only; extrapolation assumes older years help like recent ones, which the season split below tests).

## 2025 rows: same calendar month as the test month vs other months (2026 rows kept in both)

| 2025 rows kept | top 3 / 5 / 10 | diff vs all 2025 rows (95%) |
|---|---|---|
| same month only (~1/12 of 2025) | 57.6 / 68.2 / 74.8 | -3.1 [-5.1, -0.9] / -0.2 [-1.5, +1.1] / -0.9 [-1.6, -0.2] |
| other months only (~11/12) | 60.9 / 68.0 / 75.2 | +0.2 [-1.2, +1.6] / -0.4 [-1.2, +0.5] / -0.5 [-1.0, -0.0] |
