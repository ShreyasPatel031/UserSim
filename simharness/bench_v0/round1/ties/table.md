| Model (fit on VAL-HARD, scored once on HARD, 50,100 rows) | HARD AUC | mean per-launch AUC | vs round-1 logistic | vs taste-v1 |
|---|---|---|---|---|
| round-1 logistic | 0.518 [0.514, 0.523] | 0.523 [0.514, 0.533] |  |  |
| round-1 taste-v1 | 0.529 [0.519, 0.537] | 0.541 [0.529, 0.554] |  |  |
| dated ties | 0.539 [0.528, 0.549] | 0.525 [0.515, 0.535] | +0.022 [+0.008, +0.034] | +0.011 [+0.001, +0.020] |
| dated ties + logistic features | 0.547 [0.536, 0.557] | 0.547 [0.539, 0.556] | +0.030 [+0.016, +0.042] | +0.019 [+0.008, +0.028] |
| dated ties + taste-v1 | 0.544 [0.533, 0.554] | 0.548 [0.535, 0.562] | +0.027 [+0.011, +0.039] | +0.016 [+0.012, +0.020] |
| dated ties + logistic features + taste-v1 | 0.545 [0.534, 0.555] | 0.544 [0.530, 0.559] | +0.028 [+0.012, +0.040] | +0.017 [+0.012, +0.022] |
| follow ties only (undated, upper bound) | 0.531 [0.523, 0.538] | 0.519 [0.511, 0.531] | +0.013 [+0.003, +0.022] | +0.002 [-0.007, +0.011] |
| dated + follow ties (upper bound) | 0.550 [0.537, 0.563] | 0.533 [0.520, 0.550] | +0.033 [+0.017, +0.047] | +0.021 [+0.009, +0.032] |
| dated + follow ties + logistic features (upper bound) | 0.556 [0.543, 0.568] | 0.554 [0.544, 0.567] | +0.038 [+0.023, +0.052] | +0.027 [+0.016, +0.037] |
| dated + follow ties + taste-v1 (upper bound) | 0.556 [0.543, 0.568] | 0.554 [0.538, 0.573] | +0.038 [+0.021, +0.052] | +0.027 [+0.020, +0.034] |

| Tie (HARD test rows) | voters with it | matched non-voters with it |
|---|---|---|
| on the team | 0.22% (56) | 0.00% (1) |
| backed an earlier launch of the team | 67.35% (16870) | 65.72% (16463) |
| team member backed the person's earlier launch | 1.35% (338) | 0.57% (142) |
| shares an earlier upvote with a held team member | 23.76% (5953) | 21.52% (5391) |
| follows a team member (undated) | 25.94% (6497) | 20.30% (5086) |
| followed by a team member (undated) | 2.77% (694) | 1.32% (330) |
| any dated tie (team / backed / reciprocal) | 67.53% (16916) | 65.80% (16482) |
| any follow tie (undated) | 26.73% (6697) | 20.80% (5211) |

| Full pool, all test launches | recall@N | vs logistic |
|---|---|---|
| logistic | 38.5 [36.6, 40.5] |  |
| logistic + dated ties | 39.2 [37.5, 41.0] | +0.7 [+0.2, +1.1] |
| logistic + dated + follow ties (upper bound) | 39.0 [37.2, 40.8] | +0.5 [-0.1, +1.2] |
