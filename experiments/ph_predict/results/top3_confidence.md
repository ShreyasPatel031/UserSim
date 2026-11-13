# How sure are we today: confidence for the published 00:05 top 3 (arm 2, 184 scored days May-Oct, month-forward)

Pick-level: Brier 0.2230 with margins + field size vs 0.2295 position only (lower is better); base rate 0.614.

## Calibration (pick level, probability deciles)

| predicted range | picks | mean predicted | actually right |
|---|---|---|---|
| 0.30-0.47 | 56 | 0.427 | 0.536 |
| 0.47-0.50 | 55 | 0.482 | 0.345 |
| 0.50-0.53 | 55 | 0.511 | 0.527 |
| 0.53-0.56 | 55 | 0.544 | 0.473 |
| 0.56-0.60 | 55 | 0.579 | 0.691 |
| 0.60-0.65 | 55 | 0.626 | 0.655 |
| 0.65-0.70 | 55 | 0.680 | 0.545 |
| 0.70-0.75 | 55 | 0.726 | 0.782 |
| 0.75-0.80 | 55 | 0.773 | 0.800 |
| 0.80-0.93 | 56 | 0.845 | 0.786 |

## Day level: expected vs actual picks right (of 3), by tercile of day confidence

| tier | days | expected right (mean) | actual right (mean) | top-3 accuracy | all 3 right | 0-1 right |
|---|---|---|---|---|---|---|
| low | 62 | 1.64 | 1.61 | 53.8% | 8% | 44% |
| mid | 61 | 1.84 | 1.89 | 62.8% | 8% | 20% |
| high | 61 | 2.10 | 2.03 | 67.8% | 26% | 23% |

High minus low tier top-3 accuracy: +14.0 pts [+5.8, +22.1].

By pick position: #1 predicted 0.76, right 0.72; #2 predicted 0.59, right 0.64; #3 predicted 0.51, right 0.48

Frozen fit (all 214 days) -> results/frozen/top3_confidence_arm2_20261113.json for a live shadow file.
Coefficients (full fit): pos2 -0.19, pos3 -0.53, m_k4 +1.78, m_34 +0.05, m_12 -0.22, lnn -0.24

## Reading
Usable but modest. The margin over the #4 pick is the only strong input (+1.78 per log-vote unit); field size and the #1-#2 gap add little.
Calibration is within about ±10 pts per decile on 55 picks (noise at this n); the top two deciles (predicted 0.73-0.85) were right 0.78-0.80.
Day tiers separate: high-confidence days get 67.8% of top-3 picks right vs 53.8% on low days (+14.0 [+5.8, +22.1]); all three right on 26% of
high days vs 8% of low days. Suggested website wording: per pick a calibrated "about N in 10", and a day label from the tercile (sure / normal /
open), with the measured accuracy of each tier beside it. Shadow-only until it has ~30 live days; the frozen fit takes the live arm-2 score.
