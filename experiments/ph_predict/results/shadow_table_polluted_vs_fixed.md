# Forward shadow lines rebuilt on fixed inputs (today-rows bug), Oct 26 - Nov 13

As of each night (days <= d-2). polluted = all today/ files <= d plus features.py 981c5ded (what the shadows saw); fixed = today/<d> only plus 033d7bd7.
Each script's own main(d) (shadow_rebuild.py). Nights with >= 10 ranked launches. Top 3 / 5 / 10; paired day bootstrap 10,000.

| line | nights | polluted | fixed | fixed - polluted |
|---|---|---|---|---|
| old full model (unfixed) | 16 | 52.1 / 58.8 / 74.4 | 58.3 / 63.8 / 75.6 | +6.2 [-2.1, +14.6] / +5.0 [-1.2, +11.2] / +1.2 [-1.2, +3.8] |
| makerfix | 16 | 37.5 / 58.8 / 75.6 | 47.9 / 60.0 / 73.1 | +10.4 [+2.1, +20.8] / +1.2 [-2.5, +5.0] / -2.5 [-6.9, +0.6] |
| clean | 16 | 56.2 / 65.0 / 75.6 | 60.4 / 68.8 / 76.9 | +4.2 [-4.2, +12.5] / +3.8 [-1.2, +8.8] / +1.2 [+0.0, +3.1] |
| clean_nosite | 16 | 58.3 / 63.8 / 75.0 | 58.3 / 67.5 / 75.0 | +0.0 [-6.3, +6.3] / +3.8 [-2.5, +11.2] / +0.0 [-3.8, +3.1] |
| clean_avg | 16 | 58.3 / 63.8 / 75.6 | 58.3 / 70.0 / 76.2 | +0.0 [+0.0, +0.0] / +6.2 [+0.0, +11.2] / +0.6 [+0.0, +1.9] |
| h25 | 16 | 56.2 / 67.5 / 75.0 | 62.5 / 70.0 / 74.4 | +6.2 [+0.0, +12.5] / +2.5 [-2.5, +8.8] / -0.6 [-3.1, +1.9] |
| arm 2 (h25llm) | 16 | 58.3 / 66.2 / 75.6 | 60.4 / 68.8 / 75.0 | +2.1 [-4.2, +8.3] / +2.5 [-3.8, +10.0] / -0.6 [-2.5, +1.2] |
| pure (2026 only) | 16 | 54.2 / 63.8 / 75.6 | 54.2 / 66.2 / 75.0 | +0.0 [-6.2, +6.2] / +2.5 [-3.8, +10.0] / -0.6 [-3.8, +1.9] |
| readable v2 | 16 | 54.2 / 60.0 / 75.6 | 54.2 / 65.0 / 76.2 | -0.0 [-8.3, +8.3] / +5.0 [-2.5, +12.5] / +0.6 [-1.2, +2.5] |
| published (that night's model) | 16 | 52.1 / 58.8 / 74.4 | 58.3 / 63.8 / 75.6 | +6.2 [-2.1, +14.6] / +5.0 [-1.2, +11.2] / +1.2 [-1.2, +3.8] |

## On the fixed table only, paired

| comparison | nights | difference (top 3 / 5 / 10) |
|---|---|---|
| arm 2 - clean_nosite | 16 | +2.1 [-4.2, +8.3] / +1.2 [-2.5, +5.0] / +0.0 [-2.5, +2.5] |
| arm 2 - old full model | 16 | +2.1 [-4.2, +8.3] / +5.0 [-1.2, +11.2] / -0.6 [-2.5, +1.2] |
| clean_nosite - old full model | 16 | -0.0 [-8.3, +8.3] / +3.8 [-1.2, +8.8] / -0.6 [-1.9, +0.0] |
| old full model (unfixed) - published (fixed rebuild) | 16 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] |
| makerfix - published (fixed rebuild) | 16 | -10.4 [-20.8, +0.0] / -3.8 [-8.8, +1.2] / -2.5 [-5.6, +0.6] |
| clean - published (fixed rebuild) | 16 | +2.1 [-4.2, +8.3] / +5.0 [+0.0, +10.0] / +1.2 [-1.2, +3.8] |
| clean_nosite - published (fixed rebuild) | 16 | -0.0 [-8.3, +8.3] / +3.8 [-1.2, +8.8] / -0.6 [-1.9, +0.0] |
| clean_avg - published (fixed rebuild) | 16 | -0.0 [-8.3, +8.3] / +6.2 [+2.5, +11.2] / +0.6 [-1.9, +3.1] |
| h25 - published (fixed rebuild) | 16 | +4.2 [-4.2, +12.5] / +6.2 [-1.2, +12.5] / -1.2 [-3.8, +1.2] |
| arm 2 (h25llm) - published (fixed rebuild) | 16 | +2.1 [-4.2, +8.3] / +5.0 [-1.2, +11.2] / -0.6 [-2.5, +1.2] |
| pure (2026 only) - published (fixed rebuild) | 16 | -4.2 [-12.5, +4.2] / +2.5 [-2.5, +7.5] / -0.6 [-1.9, +0.0] |
| readable v2 - published (fixed rebuild) | 16 | -4.2 [-14.6, +6.2] / +1.2 [-6.2, +8.8] / +0.6 [-2.5, +3.8] |
| old full model (unfixed) (fixed) - published as it ran live | 16 | +4.2 [-6.2, +14.6] / +1.2 [-3.8, +6.2] / -0.6 [-3.8, +2.5] |
| makerfix (fixed) - published as it ran live | 16 | -6.3 [-18.8, +6.2] / -2.5 [-8.8, +3.8] / -3.1 [-7.5, +1.2] |
| clean (fixed) - published as it ran live | 16 | +6.2 [-2.1, +14.6] / +6.2 [-1.2, +12.5] / +0.6 [-2.5, +3.8] |
| clean_nosite (fixed) - published as it ran live | 16 | +4.2 [-6.3, +14.6] / +5.0 [-1.2, +11.2] / -1.2 [-4.4, +1.9] |
| clean_avg (fixed) - published as it ran live | 16 | +4.2 [-6.3, +14.6] / +7.5 [+1.2, +13.8] / +0.0 [-3.1, +3.8] |
| h25 (fixed) - published as it ran live | 16 | +8.3 [-0.0, +16.7] / +7.5 [+2.5, +12.5] / -1.9 [-6.2, +1.9] |
| arm 2 (h25llm) (fixed) - published as it ran live | 16 | +6.2 [-2.1, +14.6] / +6.2 [+2.5, +11.2] / -1.2 [-5.0, +2.5] |
| pure (2026 only) (fixed) - published as it ran live | 16 | -0.0 [-12.5, +12.5] / +3.8 [-2.5, +10.0] / -1.2 [-4.4, +1.9] |
| readable v2 (fixed) - published as it ran live | 16 | -0.0 [-10.4, +10.4] / +2.5 [-3.8, +8.8] / +0.0 [-3.8, +4.4] |

Cross-check: the old full model rows (polluted 52.1 / 58.8 / 74.4, fixed 58.3 / 63.8 / 75.6) match today_replay.py exactly, a separate code path.
h25 and arm 2 now differ (max |pred difference| 0.22 / 0.21): the rerun links the Gemini 2025 dirs that the first pass missed.

## Pre-reveal lines (12-day study, prereveal_12day.py, frozen hr_clean weights; 11 scored days, top 3 / 5 / 10)

| line | prior: live parquet | prior: polluted replay | prior: fixed replay |
|---|---|---|---|
| P1 hr_clean (published P1) | 69.7 / 65.5 / 75.5 | 69.7 / 65.5 / 75.5 | 69.7 / 67.3 / 75.5 |
| P2 hr_clean (published P2) | 69.7 / 72.7 / 74.5 | 69.7 / 72.7 / 74.5 | 75.8 / 72.7 / 75.5 |
| P345 hybrid (published) | 72.7 / 76.4 / 77.3 | 72.7 / 76.4 / 77.3 | 72.7 / 76.4 / 78.2 |
| P3 hr_clean LODO - hidden | top 10 +3.6 [+0.9, +6.4] | +4.5 [+1.8, +7.3] | +7.3 [+4.5, +10.0] |
| P345 hr_clean LODO - hidden | top 10 +3.6 [+0.0, +7.3] | +3.6 [+0.0, +7.3] | +4.5 [+0.9, +8.2] |

slots6_prior and hidden_0030 / hidden_0100 use the month-fold arm-2 backtest prior (never built from today/), so the bug does not touch them.
The velocity V lines use votes only, so they are not affected either.

## Answers (fixed table only)
1. Arm 2 vs clean_nosite vs old full model, 16 nights, paired. arm 2 - clean_nosite +2.1 [-4.2, +8.3] top 3; arm 2 - old full model +2.1 [-4.2, +8.3]
   (top 5 +5.0 [-1.2, +11.2]); clean_nosite - old full model 0.0 [-8.3, +8.3]. The order arm 2 > clean_nosite >= old full model matches the
   183-day backtest, but 16 nights cannot separate them.
2. Against the published line (fixed rebuild, same nights): no shadow line beats it on top 3 with the interval clear of 0. On top 5,
   clean_avg +6.2 [+2.5, +11.2] and clean +5.0 [+0.0, +10.0] (edge). Against the line as it actually ran live, arm 2 (fixed) is +6.2 [+2.5, +11.2]
   top 5 and h25 (fixed) +7.5 [+2.5, +12.5] top 5, but those comparisons mix the bug fix and the model change. makerfix is worse (-10.4 top 3).
3. hr_clean: the "not established" top-3 verdict does not change. P2 hr_clean top 3 69.7 -> 75.8 on the fixed prior, but the LODO top-3 edge over
   hidden is +6.1 [-6.1, +18.2]. The top-10 edges, already clear of 0, get larger (P3 +7.3 [+4.5, +10.0]). Velocity is unaffected (votes only).
