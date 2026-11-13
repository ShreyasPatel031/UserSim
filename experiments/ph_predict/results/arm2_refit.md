# Arm 2 re-fit choices with the doubled training set (orchestrator 20:32Z Nov 13)

214 days (Apr-Oct), walk-forward, 5 seeds, paired vs deployed arm 2 (60.7 / 68.4 / 75.7; first 107 62.6 / last 107 58.9 top 3). Each group's choice is picked on the first 107 days only, then frozen.

| group | chosen (on first 107) | first-107 top 3 diff | last 107: top 3 / 5 / 10 diff [95%] | all 214: top 3 / 5 / 10 diff [95%] | rule 5 |
|---|---|---|---|---|---|
| a) capacity | cap_l15_m50_n400 | -1.2 | -0.3 [-1.6, +0.9] / -0.7 [-2.1, +0.6] / -0.2 [-0.7, +0.3] | -0.8 [-2.0, +0.3] / -0.6 [-1.5, +0.3] / -0.1 [-0.4, +0.2] | no |
| b) row weighting | w_y050 | +0.3 | -1.6 [-3.1, -0.0] / -0.7 [-1.7, +0.2] / -0.6 [-1.1, -0.1] | -0.6 [-2.0, +0.8] / -0.2 [-1.0, +0.7] / -0.3 [-0.7, +0.2] | no |
| c) objective (LambdaRank) | obj_lr10 | -3.4 | +0.9 [-1.6, +3.7] / -0.2 [-2.1, +1.5] / -0.5 [-1.4, +0.5] | -1.2 [-3.4, +0.8] / +0.0 [-1.1, +1.2] / -0.3 [-1.0, +0.3] | no |
| d) rank blend with readable v2 stumps | blend_stumps_0.2 | +0.3 | +0.3 [+0.0, +0.9] / -0.2 [-0.6, +0.0] / +0.0 [-0.4, +0.4] | +0.3 [-0.3, +0.9] / +0.0 [-0.6, +0.6] / +0.2 [-0.1, +0.6] | no |
| d) rank blend with readable ridge | blend_ridge10_0.1 | +0.0 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +0.1 [-0.2, +0.4] | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +0.1 [-0.1, +0.3] | no |

## Every candidate (top 3 / 5 / 10 diff vs arm 2; first 107 | last 107 | all)

| candidate | first 107 | last 107 | all |
|---|---|---|---|
| cap_l15_m20_n800 | -2.8 / -0.6 / -0.1 | +0.3 / -0.7 / -0.6 | -1.2 / -0.7 / -0.3 |
| cap_l15_m20_n800_lr015 | -1.6 / +0.2 / +0.1 | +0.0 / -0.4 / -0.3 | -0.8 / -0.1 / -0.1 |
| cap_l15_m50_n400 | -1.2 / -0.4 / +0.0 | -0.3 / -0.7 / -0.2 | -0.8 / -0.6 / -0.1 |
| cap_l15_m50_n800 | -3.1 / -1.3 / -0.2 | +0.9 / -0.9 / -0.2 | -1.1 / -1.1 / -0.2 |
| cap_l31_m20_n400 | -2.2 / +0.0 / +0.0 | +0.0 / -0.7 / -0.4 | -1.1 / -0.4 / -0.2 |
| cap_l31_m20_n800 | -3.4 / +0.4 / +0.1 | -0.3 / -0.7 / -0.7 | -1.9 / -0.2 / -0.3 |
| cap_l31_m50_n1200_lr02 | -4.0 / -1.5 / +0.0 | +1.2 / -1.1 / -0.3 | -1.4 / -1.3 / -0.1 |
| cap_l31_m50_n400 | -1.6 / -0.6 / +0.2 | +0.6 / -0.7 / -0.2 | -0.5 / -0.7 / +0.0 |
| cap_l31_m50_n800 | -4.0 / -1.3 / +0.0 | -0.9 / -1.1 / -0.7 | -2.5 / -1.2 / -0.4 |
| cap_l63_m20_n400 | -1.6 / -0.6 / +0.1 | +1.2 / -0.7 / -0.5 | -0.2 / -0.7 / -0.2 |
| cap_l63_m20_n800 | -4.4 / +0.2 / -0.2 | +0.9 / -0.6 / -0.5 | -1.7 / -0.2 / -0.3 |
| cap_l63_m50_n800 | -2.8 / -0.6 / -0.2 | +0.3 / -1.9 / -0.7 | -1.2 / -1.2 / -0.4 |
| obj_lr10 | -3.4 / +0.2 / -0.2 | +0.9 / -0.2 / -0.5 | -1.2 / +0.0 / -0.3 |
| obj_lr3 | -3.4 / -1.5 / -0.5 | -0.0 / -0.9 / -1.6 | -1.7 / -1.2 / -1.0 |
| w_hl180 | -0.9 / +0.7 / +0.0 | -1.2 / -1.1 / -0.7 | -1.1 / -0.2 / -0.3 |
| w_hl365 | -0.3 / +0.0 / +0.0 | +0.6 / -0.6 / -0.7 | +0.2 / -0.3 / -0.3 |
| w_hl90 | -2.8 / +0.7 / +0.7 | -2.5 / -0.9 / -1.1 | -2.6 / -0.1 / -0.2 |
| w_y050 | +0.3 / +0.4 / +0.0 | -1.6 / -0.7 / -0.6 | -0.6 / -0.2 / -0.3 |
| w_y075 | -0.6 / +0.2 / +0.2 | +0.0 / -0.7 / -0.5 | -0.3 / -0.3 / -0.1 |
| blend_stumps_0.1 | +0.0 / +0.2 / +0.2 | +0.0 / +0.0 / +0.1 | +0.0 / +0.1 / +0.1 |
| blend_stumps_0.2 | +0.3 / +0.2 / +0.5 | +0.3 / -0.2 / +0.0 | +0.3 / +0.0 / +0.2 |
| blend_stumps_0.3 | -1.6 / +0.0 / +0.3 | +0.3 / -0.6 / +0.0 | -0.6 / -0.3 / +0.1 |
| blend_stumps_0.4 | -2.8 / -0.2 / +0.4 | -0.9 / -0.2 / +0.5 | -1.9 / -0.2 / +0.4 |
| blend_stumps_0.5 | -3.7 / -0.2 / +0.3 | -2.2 / +0.2 / +0.3 | -3.0 / +0.0 / +0.3 |
| blend_ridge10_0.1 | +0.0 / +0.0 / +0.1 | +0.0 / +0.0 / +0.1 | +0.0 / +0.0 / +0.1 |
| blend_ridge10_0.2 | -0.3 / -0.4 / -0.2 | +0.0 / -0.2 / +0.0 | -0.2 / -0.3 / -0.1 |
| blend_ridge10_0.3 | -2.8 / -1.5 / -0.4 | +0.0 / -0.4 / -0.1 | -1.4 / -0.9 / -0.2 |
| blend_ridge10_0.4 | -3.4 / -2.6 / -0.6 | +0.0 / +0.2 / -0.7 | -1.7 / -1.2 / -0.6 |
| blend_ridge10_0.5 | -3.7 / -3.6 / -0.7 | -0.9 / +0.9 / -0.5 | -2.3 / -1.3 / -0.6 |

## Verdict
Nothing qualifies; nothing deployed. Every capacity, weighting and objective setting chosen on the first 107 days is at or below deployed arm 2 on
all 214 days (top 3 -0.6 to -1.2). The deployed settings (15 leaves, 20 min rows, 400 trees, lr 0.03, regression on log votes, all rows weight 1)
are still the best of the grid on the doubled set. The only non-negative choice is a 0.2 rank blend with the readable v2 stumps: +0.3 [-0.3, +0.9] top 3
on all days, noise. LambdaRank (NDCG@3 / @10) was run before only on the 2026-only half-size set (objective_lineup.md: +1.2 / +0.5 top 3, within noise);
on arm 2 it is -1.7 / -1.2 on all days.
