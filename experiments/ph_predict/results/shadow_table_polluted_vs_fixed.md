> PARTIAL (Nov 14 ~18:35Z): 12-14 of 16 nights, and the h25 / arm 2 rows are INVALID. The scratch h25 root lacked the Gemini 2025 dirs, so h25llm equalled h25. A rerun is in progress; this file will be replaced.

# Forward shadow lines rebuilt on fixed inputs (today-rows bug), Oct 26 - Nov 13

As of each night (days <= d-2). polluted = all today/ files <= d plus features.py 981c5ded (what the shadows saw); fixed = today/<d> only plus 033d7bd7.
Each script's own main(d) (shadow_rebuild.py). Nights with >= 10 ranked launches. Top 3 / 5 / 10; paired day bootstrap 10,000.

| line | nights | polluted | fixed | fixed - polluted |
|---|---|---|---|---|
| old full model (unfixed) | 14 | 52.4 / 57.1 / 72.9 | 59.5 / 62.9 / 73.6 | +7.1 [-2.4, +16.7] / +5.7 [-1.4, +12.9] / +0.7 [-1.4, +2.9] |
| makerfix | 14 | 40.5 / 60.0 / 75.0 | 47.6 / 60.0 / 72.1 | +7.1 [+0.0, +14.3] / +0.0 [-4.3, +4.3] / -2.9 [-7.9, +1.4] |
| clean | 14 | 57.1 / 64.3 / 73.6 | 61.9 / 68.6 / 75.0 | +4.8 [-4.8, +14.3] / +4.3 [-1.4, +10.0] / +1.4 [+0.0, +3.6] |
| clean_nosite | 14 | 59.5 / 62.9 / 73.6 | 59.5 / 67.1 / 72.9 | +0.0 [-7.1, +7.1] / +4.3 [-2.9, +12.9] / -0.7 [-4.3, +2.9] |
| clean_avg | 14 | 59.5 / 62.9 / 73.6 | 59.5 / 68.6 / 74.3 | +0.0 [+0.0, +0.0] / +5.7 [+0.0, +11.4] / +0.7 [+0.0, +2.1] |
| h25 | 12 | 58.3 / 70.0 / 75.0 | 63.9 / 73.3 / 74.2 | +5.6 [+0.0, +13.9] / +3.3 [+0.0, +10.0] / -0.8 [-4.2, +2.5] |
| arm 2 (h25llm) | 12 | 58.3 / 70.0 / 75.0 | 63.9 / 73.3 / 74.2 | +5.6 [+0.0, +13.9] / +3.3 [+0.0, +10.0] / -0.8 [-4.2, +2.5] |
| pure (2026 only) | 12 | 55.6 / 66.7 / 75.8 | 58.3 / 68.3 / 75.0 | +2.8 [+0.0, +8.3] / +1.7 [-6.7, +11.7] / -0.8 [-5.0, +2.5] |
| readable v2 | 12 | 63.9 / 61.7 / 75.0 | 58.3 / 70.0 / 75.8 | -5.6 [-13.9, +0.0] / +8.3 [+0.0, +16.7] / +0.8 [-1.7, +3.3] |
| published (that night's model) | 14 | 52.4 / 57.1 / 72.9 | 59.5 / 62.9 / 73.6 | +7.1 [-2.4, +16.7] / +5.7 [-1.4, +12.9] / +0.7 [-1.4, +2.9] |

## On the fixed table only, paired

| comparison | nights | difference (top 3 / 5 / 10) |
|---|---|---|
| arm 2 - clean_nosite | 12 | +2.8 [-5.6, +11.1] / +3.3 [+0.0, +8.3] / +0.0 [-3.3, +3.3] |
| arm 2 - old full model | 12 | +2.8 [-5.6, +11.1] / +10.0 [+5.0, +15.0] / -0.8 [-3.3, +1.7] |
| clean_nosite - old full model | 14 | -0.0 [-9.5, +9.5] / +4.3 [-1.4, +10.0] / -0.7 [-2.1, +0.0] |
| old full model (unfixed) - published (fixed rebuild) | 14 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] |
| makerfix - published (fixed rebuild) | 14 | -11.9 [-21.4, -0.0] / -2.9 [-8.6, +2.9] / -1.4 [-5.0, +2.1] |
| clean - published (fixed rebuild) | 14 | +2.4 [-4.8, +9.5] / +5.7 [+0.0, +11.4] / +1.4 [-1.4, +4.3] |
| clean_nosite - published (fixed rebuild) | 14 | -0.0 [-9.5, +9.5] / +4.3 [-1.4, +10.0] / -0.7 [-2.1, +0.0] |
| clean_avg - published (fixed rebuild) | 14 | -0.0 [-9.5, +9.5] / +5.7 [+1.4, +10.0] / +0.7 [-2.1, +3.6] |
| h25 - published (fixed rebuild) | 12 | +2.8 [-5.6, +11.1] / +10.0 [+5.0, +15.0] / -0.8 [-3.3, +1.7] |
| arm 2 (h25llm) - published (fixed rebuild) | 12 | +2.8 [-5.6, +11.1] / +10.0 [+5.0, +15.0] / -0.8 [-3.3, +1.7] |
| pure (2026 only) - published (fixed rebuild) | 12 | -2.8 [-11.1, +5.6] / +5.0 [+0.0, +10.0] / +0.0 [+0.0, +0.0] |
| readable v2 - published (fixed rebuild) | 12 | -2.8 [-11.1, +5.6] / +6.7 [+1.7, +11.7] / +0.8 [-3.3, +5.8] |
| old full model (unfixed) (fixed) - published as it ran live | 14 | +4.8 [-7.1, +16.7] / +2.9 [-2.9, +8.6] / -1.4 [-5.0, +2.1] |
| makerfix (fixed) - published as it ran live | 14 | -7.1 [-19.1, +4.8] / +0.0 [-5.7, +5.7] / -2.9 [-7.9, +2.1] |
| clean (fixed) - published as it ran live | 14 | +7.1 [-2.4, +16.7] / +8.6 [+1.4, +14.3] / +0.0 [-3.6, +3.6] |
| clean_nosite (fixed) - published as it ran live | 14 | +4.8 [-7.1, +16.7] / +7.1 [+0.0, +12.9] / -2.1 [-5.7, +1.4] |
| clean_avg (fixed) - published as it ran live | 14 | +4.8 [-7.1, +16.7] / +8.6 [+1.4, +14.3] / -0.7 [-4.3, +2.9] |
| h25 (fixed) - published as it ran live | 12 | +8.3 [-2.8, +19.5] / +10.0 [+5.0, +15.0] / -1.7 [-5.0, +2.5] |
| arm 2 (h25llm) (fixed) - published as it ran live | 12 | +8.3 [-2.8, +19.5] / +10.0 [+5.0, +15.0] / -1.7 [-5.8, +2.5] |
| pure (2026 only) (fixed) - published as it ran live | 12 | +2.8 [-8.4, +13.9] / +5.0 [-1.7, +11.7] / -0.8 [-4.2, +2.5] |
| readable v2 (fixed) - published as it ran live | 12 | +2.8 [-8.4, +13.9] / +6.7 [+0.0, +13.3] / +0.0 [-5.0, +5.0] |
