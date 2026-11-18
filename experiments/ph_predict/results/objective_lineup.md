# 00:05 launch model: objective / ensemble and same-day line-up features (honest, month-forward)

245 days, 5,709 launches; 5 seeds; paired day-bootstrap 95% CI vs reg.

| variant | top 3 | top 5 | top 10 | minus reg: top 3 | top 5 | top 10 |
|---|---|---|---|---|---|---|
| reg | 59.9 | 67.7 | 75.4 | +0.0 [+0.0, +0.0] | +0.0 [+0.0, +0.0] | +0.0 [+0.0, +0.0] |
| lr_ndcg | 61.2 | 68.1 | 74.3 | +1.2 [-0.5, +3.2] | +0.3 [-1.0, +1.7] | -1.2 [-2.0, -0.4] |
| lr_top3 | 60.5 | 67.9 | 73.7 | +0.5 [-1.2, +2.3] | +0.2 [-1.2, +1.6] | -1.8 [-2.6, -0.9] |
| clf3 | 61.6 | 66.7 | 73.4 | +1.6 [-0.4, +3.8] | -1.1 [-2.6, +0.3] | -2.1 [-3.0, -1.1] |
| clf10 | 56.2 | 66.9 | 75.5 | -3.7 [-6.4, -0.8] | -0.8 [-2.3, +0.7] | +0.1 [-0.9, +1.0] |
| ridge | 21.3 | 33.5 | 50.3 | -38.7 [-42.5, -34.7] | -34.2 [-37.4, -31.0] | -25.1 [-27.8, -22.4] |
| avg3 | 51.0 | 62.1 | 71.9 | -8.9 [-11.8, -6.0] | -5.7 [-7.6, -3.8] | -3.5 [-4.8, -2.3] |
| avg2 | 61.2 | 68.3 | 75.1 | +1.2 [-0.1, +2.6] | +0.6 [-0.4, +1.6] | -0.3 [-1.0, +0.3] |
| reg_lu | 60.1 | 67.7 | 75.5 | +0.1 [-1.0, +1.2] | +0.0 [-0.9, +0.9] | +0.0 [-0.4, +0.5] |
| stage2 | 61.6 | 68.5 | 75.8 | +0.8 [-0.3, +1.9] | +0.1 [-0.5, +0.8] | +0.2 [-0.5, +0.8] |

## Reading

**Prior work.** These were tested before only on the pre-honest feature set:
- rank_launch.py: LambdaRank +0.6 top 3, within noise.
- dayexp.py: clf3, clf5, rank and blends all within ±0.4 of regression.
- ctx_features.py: within-day percentile and gap features.
- day_strength.py: day-level vote pool.

Same-day text similarity, topic crowding and the LM-relative second stage are new.

**1. Objective / ensemble on the honest set: no significant top-3 gain.**
- LambdaRank, the top-3 classifier and reg + LambdaRank all gain +1.2 to +1.6 top 3, with intervals touching 0. They lose 1–2 points on top 10, significantly for LambdaRank and clf3.
- The top-3-weighted LambdaRank is no better than plain LambdaRank.
- The top-10 classifier loses −3.7 top 3.
- Ridge on raw honest columns is far worse (21 / 34 / 50), so the 3-way rank average is worse too. Without ridge, the reg + LambdaRank average gives +1.2 [−0.1, +2.6] / +0.6 / −0.3: the most balanced variant, still within noise.

**2. Same-day line-up competition: null.**
- Adding topic crowding plus max and mean text similarity to the day's other launches inside the model: +0.1 / 0.0 / 0.0.
- A second stage on the out-of-fold LM score, adding score gap to the day's best, the day's top-5 strength and the line-up features: +0.8 [−0.3, +1.9] / +0.1 / +0.2, on 214 days.
- The near-duplicate-of-a-higher-launch flag was not built separately. The max-similarity input carries it, and it adds nothing.
