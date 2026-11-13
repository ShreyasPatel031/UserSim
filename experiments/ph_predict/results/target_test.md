# Training target: official dailyRank vs later-read votes (214 days Apr-Oct 2026, month walk-forward, 5 seeds, arm 2 for the 2025 arm)

| arm | target | top 3 | top 5 | top 10 | rho | diff vs later-read votes (t3 / t5 / t10 / rho, 95%) |
|---|---|---|---|---|---|---|
| pure | later-read log votes (deployed) | 56.9 | 67.6 | 75.0 | 0.613 | - |
| pure | -log(dailyRank) | 56.7 | 67.9 | 75.4 | 0.622 | -0.2 [-2.5, +2.2] / +0.4 [-0.9, +1.6] / +0.5 [-0.1, +1.1] / +0.008 [-0.004, +0.021] (214 days) |
| pure | log votes in dailyRank order | 56.5 | 68.1 | 74.7 | 0.619 | -0.3 [-1.9, +1.2] / +0.6 [-0.3, +1.4] / -0.2 [-0.7, +0.3] / +0.006 [-0.003, +0.016] (214 days) |
| both | later-read log votes (deployed) | 60.7 | 68.4 | 75.7 | 0.642 | - |
| both | -log(dailyRank) | 60.1 | 67.7 | 75.0 | 0.632 | -0.6 [-2.8, +1.7] / -0.7 [-2.1, +0.6] / -0.7 [-1.4, -0.1] / -0.010 [-0.019, -0.000] (214 days) |
| both | log votes in dailyRank order | 59.8 | 68.7 | 75.2 | 0.637 | -0.9 [-2.3, +0.6] / +0.3 [-0.7, +1.3] / -0.5 [-1.0, +0.0] / -0.005 [-0.011, +0.001] (214 days) |
