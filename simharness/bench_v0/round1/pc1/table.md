**Presence: everyone, history complete through D-1 (read later)** (56878 person-days)

| Model | AUC (mean per day) | ECE | voters in top N | vs baseline (top N) |
|---|---|---|---|---|
| baseline | 0.874 [0.858, 0.889] | 0.013 [0.010, 0.030] | 61.0 [60.3, 61.7] |  |
| logistic | 0.897 [0.882, 0.911] | 0.008 [0.005, 0.025] | 65.4 [63.8, 66.7] | +4.4 [+2.8, +5.9] |
| lgbm | 0.898 [0.883, 0.912] | 0.005 [0.004, 0.019] | 65.4 [63.9, 66.6] | +4.4 [+2.9, +5.7] |

**Presence: everyone, history as known at 00:05** (56878 person-days)

| Model | AUC (mean per day) | ECE | voters in top N | vs baseline (top N) |
|---|---|---|---|---|
| baseline | 0.562 [0.548, 0.576] | 0.132 [0.103, 0.171] | 38.3 [36.9, 39.7] |  |
| logistic | 0.565 [0.552, 0.579] | 0.146 [0.117, 0.185] | 37.8 [36.4, 39.2] | -0.5 [-1.1, -0.0] |
| lgbm | 0.534 [0.521, 0.547] | 0.146 [0.118, 0.186] | 27.7 [24.9, 30.0] | -10.6 [-12.7, -9.0] |

**Presence: people read on D-1, history as known at 00:05**: 0 person-days, not scored

**Presence: people read within 7 days before D, history as known at 00:05**: 0 person-days, not scored

**Presence: people read within 7 days before D, history complete through D-1**: 0 person-days, not scored

**Choice (test person-days, 00:05 line-up)**

| Model | top-3 hit | MRR | AUC | top-3 vs structural |
|---|---|---|---|---|
| structural order | 60.9 [52.7, 70.2] | 0.459 [0.388, 0.532] | 0.774 [0.754, 0.795] |  |
| topic match | 22.6 [17.7, 27.9] | 0.231 [0.196, 0.269] | 0.582 [0.532, 0.627] | -38.3 [-47.1, -29.5] |
| taste-v1 | 31.5 [25.5, 38.3] | 0.291 [0.246, 0.339] | 0.603 [0.563, 0.638] | -29.4 [-38.1, -21.8] |
| dated ties | 44.6 [37.6, 52.4] | 0.391 [0.338, 0.451] | 0.671 [0.637, 0.699] | -16.3 [-23.9, -7.2] |
| combination (logistic, fit on validation) | 61.5 [53.0, 69.7] | 0.498 [0.438, 0.567] | 0.788 [0.766, 0.807] | +0.5 [-8.3, +7.5] |
| random order | 23.8 [20.3, 28.3] | 0.235 [0.206, 0.272] | 0.499 [0.494, 0.503] | -37.1 [-43.6, -31.0] |

**Language models on CHOICE (fixed subsample)**

| Model | top-3 hit | MRR | AUC | top-3 vs structural | top-3 vs combination | $ / 1k | picks in first fifth of the list |
|---|---|---|---|---|---|---|---|
| structural order (same person-days) | 60.3 [51.7, 68.3] | 0.450 [0.382, 0.516] | 0.751 [0.730, 0.770] |  |  |  |  |
| combination (logistic, fit on validation) (same person-days) | 62.0 [55.3, 68.0] | 0.482 [0.429, 0.542] | 0.769 [0.751, 0.788] |  |  |  |  |
| taste-v1 (same person-days) | 32.0 [23.7, 40.3] | 0.288 [0.228, 0.349] | 0.594 [0.563, 0.622] |  |  |  |  |
| random order (same person-days) | 24.7 [19.0, 30.3] | 0.243 [0.189, 0.302] | 0.491 [0.473, 0.511] |  |  |  |  |
| gemini-2.5-flash | 32.7 [24.3, 41.3] | 0.310 [0.244, 0.384] | 0.528 [0.503, 0.555] | -27.7 [-37.3, -19.0] | -29.3 [-38.0, -20.0] | 0.9941 | 0.269 |
| gpt-oss-120b | 32.7 [24.3, 41.0] | 0.304 [0.235, 0.381] | 0.537 [0.513, 0.563] | -27.7 [-37.7, -18.3] | -29.3 [-38.0, -20.7] | 0.5766 | 0.375 |
| llama-4-maverick | 27.7 [20.3, 35.3] | 0.272 [0.210, 0.339] | 0.515 [0.499, 0.530] | -32.7 [-40.3, -25.3] | -34.3 [-41.7, -26.0] | 1.0783 | 0.44 |

**Launch order from the simulated members' pick counts (all test person-days)**

| Model | top-3 hit | MRR | AUC | top-3 vs structural |
|---|---|---|---|---|
| gemini-2.5-flash | 32.5 [26.9, 38.0] | 0.268 [0.234, 0.310] | 0.579 [0.548, 0.611] | -28.4 [-36.4, -21.0] |
| gpt-oss-120b | 28.2 [21.1, 35.6] | 0.292 [0.233, 0.360] | 0.588 [0.534, 0.643] | -32.7 [-41.2, -25.4] |
| llama-4-maverick | 30.8 [24.5, 37.0] | 0.281 [0.224, 0.349] | 0.569 [0.503, 0.631] | -30.1 [-40.4, -20.6] |

**Full pool, all test launches**

| Model | recall@N | vs logistic | vs logistic + ties |
|---|---|---|---|
| P(present) alone [lgbm] | 25.1 [23.3, 27.1] | -13.4 [-15.9, -11.0] | -14.1 [-16.3, -11.9] |
| P(present, logistic) x P(choose | present) | 39.3 [37.6, 41.3] | +0.8 [+0.4, +1.3] | +0.1 [-0.4, +0.7] |
| P(present, lgbm) x P(choose | present) | 38.7 [37.2, 40.5] | +0.2 [-0.4, +0.9] | -0.5 [-1.2, +0.3] |
| P(choose | present) alone | 26.7 [24.9, 28.2] | -11.8 [-13.2, -10.6] | -12.5 [-13.9, -11.3] |
| ORACLE presence x P(choose | present) (diagnostic: uses the day's outcome) | 44.1 [42.0, 46.6] | +5.6 [+4.4, +6.9] | +4.9 [+3.8, +6.1] |
| logistic (round 1) | 38.5 [36.6, 40.5] |  |  |
| logistic + dated ties (TIES-1) | 39.2 [37.5, 41.0] |  |  |
