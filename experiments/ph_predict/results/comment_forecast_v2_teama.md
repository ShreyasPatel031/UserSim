# Pre-reveal forecast from comments (hours 0-4 PT), backtest

Days: 238 launch days (2026-03-01 to 2026-10-24) with >= 80% of the ranked line-up in the comment dump and an honest pre-launch LM prediction; 102,128 comments on 6,490 launch pages. Scored months: all but the first (month-forward training).

| cut (PT) | scorer | top 3 | top 5 | top 10 | Spearman | days |
|---|---|---|---|---|---|---|
| 00:00+1h | LM only | 57.6 [54, 61] | 68.2 [66, 71] | 74.7 [73, 76] | 62.8 [60, 65] | 207 |
| 00:00+1h | comment count only | 53.6 [50, 57] | 62.4 [60, 65] | 71.3 [69, 73] | 54.9 [52, 58] | 207 |
| | _minus LM_ | -4.0 [-8, +0] | -5.8 [-8, -3] | -3.5 [-5, -2] | -7.9 [-11, -5] | |
| 00:00+1h | combiner (LightGBM) | 60.2 [57, 63] | 67.6 [65, 70] | 74.8 [73, 77] | 62.1 [59, 65] | 207 |
| | _minus LM_ | +2.6 [-0, +6] | -0.6 [-3, +1] | +0.0 [-1, +1] | -0.7 [-3, +1] | |
| 00:00+1h | combiner (ridge) | 63.8 [60, 67] | 70.9 [68, 73] | 75.8 [74, 77] | 65.7 [63, 68] | 207 |
| | _minus LM_ | +6.1 [+3, +9] | +2.7 [+1, +5] | +1.1 [+0, +2] | +2.9 [+2, +4] | |
| 00:00+1h | ablation: ridge, LM features only | 57.6 [54, 61] | 68.2 [66, 71] | 74.7 [73, 76] | 62.8 [60, 65] | 207 |
| | _minus LM_ | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | |
| 00:00+1h | ablation: ridge, no account flags | 64.1 [61, 67] | 71.4 [69, 74] | 75.9 [74, 78] | 65.9 [64, 68] | 207 |
| | _minus LM_ | +6.4 [+3, +10] | +3.2 [+1, +5] | +1.2 [+0, +2] | +3.1 [+2, +4] | |
| 00:00+2h | LM only | 57.6 [54, 61] | 68.2 [65, 71] | 74.7 [73, 76] | 62.8 [60, 65] | 207 |
| 00:00+2h | comment count only | 55.7 [52, 59] | 63.4 [61, 66] | 70.3 [68, 72] | 55.2 [52, 58] | 207 |
| | _minus LM_ | -1.9 [-6, +2] | -4.8 [-8, -2] | -4.4 [-6, -3] | -7.7 [-11, -5] | |
| 00:00+2h | combiner (LightGBM) | 62.2 [59, 65] | 70.0 [67, 72] | 76.4 [74, 78] | 64.6 [62, 67] | 207 |
| | _minus LM_ | +4.5 [+1, +8] | +1.7 [-1, +4] | +1.6 [+1, +3] | +1.8 [-0, +4] | |
| 00:00+2h | combiner (ridge) | 66.3 [63, 70] | 72.6 [70, 75] | 76.7 [75, 78] | 67.8 [66, 70] | 207 |
| | _minus LM_ | +8.7 [+5, +12] | +4.3 [+2, +7] | +1.9 [+1, +3] | +5.0 [+3, +7] | |
| 00:00+2h | ablation: ridge, LM features only | 57.6 [54, 61] | 68.2 [66, 71] | 74.7 [73, 76] | 62.8 [60, 65] | 207 |
| | _minus LM_ | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | |
| 00:00+2h | ablation: ridge, no account flags | 66.2 [63, 69] | 72.6 [70, 75] | 76.6 [75, 78] | 67.6 [65, 70] | 207 |
| | _minus LM_ | +8.5 [+5, +12] | +4.3 [+2, +6] | +1.8 [+1, +3] | +4.7 [+3, +6] | |
| 00:00+3h | LM only | 57.6 [54, 61] | 68.2 [66, 71] | 74.7 [73, 76] | 62.8 [60, 65] | 207 |
| 00:00+3h | comment count only | 56.0 [52, 59] | 64.1 [61, 67] | 69.9 [68, 72] | 54.2 [51, 57] | 207 |
| | _minus LM_ | -1.6 [-6, +3] | -4.2 [-7, -1] | -4.9 [-7, -3] | -8.7 [-12, -5] | |
| 00:00+3h | combiner (LightGBM) | 63.3 [60, 66] | 71.5 [69, 74] | 76.0 [74, 78] | 64.9 [62, 67] | 207 |
| | _minus LM_ | +5.6 [+2, +9] | +3.3 [+1, +6] | +1.3 [+0, +2] | +2.1 [+0, +4] | |
| 00:00+3h | combiner (ridge) | 67.1 [64, 70] | 72.3 [70, 75] | 77.1 [75, 79] | 68.2 [66, 70] | 207 |
| | _minus LM_ | +9.5 [+6, +13] | +4.1 [+2, +6] | +2.3 [+1, +3] | +5.4 [+4, +7] | |
| 00:00+3h | ablation: ridge, LM features only | 57.6 [54, 61] | 68.2 [66, 71] | 74.7 [73, 76] | 62.8 [60, 65] | 207 |
| | _minus LM_ | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | |
| 00:00+3h | ablation: ridge, no account flags | 67.5 [64, 70] | 72.6 [70, 75] | 76.9 [75, 79] | 68.3 [66, 70] | 207 |
| | _minus LM_ | +9.8 [+6, +13] | +4.3 [+2, +7] | +2.2 [+1, +3] | +5.5 [+4, +7] | |
| 00:00+4h | LM only | 57.6 [54, 61] | 68.2 [66, 71] | 74.7 [73, 76] | 62.8 [60, 65] | 207 |
| 00:00+4h | comment count only | 58.0 [55, 61] | 64.6 [62, 67] | 69.8 [68, 72] | 54.0 [51, 57] | 207 |
| | _minus LM_ | +0.3 [-4, +5] | -3.6 [-6, -1] | -5.0 [-7, -3] | -8.9 [-12, -6] | |
| 00:00+4h | combiner (LightGBM) | 63.6 [61, 66] | 70.5 [68, 73] | 76.8 [75, 79] | 64.8 [62, 67] | 207 |
| | _minus LM_ | +6.0 [+2, +10] | +2.3 [+0, +4] | +2.1 [+1, +3] | +1.9 [-0, +4] | |
| 00:00+4h | combiner (ridge) | 67.0 [64, 70] | 72.6 [70, 75] | 77.5 [76, 79] | 69.0 [66, 71] | 207 |
| | _minus LM_ | +9.3 [+6, +12] | +4.3 [+2, +7] | +2.8 [+2, +4] | +6.1 [+4, +8] | |
| 00:00+4h | ablation: ridge, LM features only | 57.6 [54, 61] | 68.2 [66, 71] | 74.7 [73, 76] | 62.8 [60, 65] | 207 |
| | _minus LM_ | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | |
| 00:00+4h | ablation: ridge, no account flags | 66.8 [64, 70] | 72.9 [70, 75] | 77.3 [76, 79] | 68.5 [66, 71] | 207 |
| | _minus LM_ | +9.2 [+6, +12] | +4.6 [+3, +7] | +2.6 [+2, +4] | +5.7 [+4, +8] | |

Comments per launch by cut: +1h mean 2.1, 7% with none; +2h mean 3.1, 6% with none; +3h mean 4.1, 6% with none; +4h mean 4.9, 5% with none

Leak checks: features use created_at <= T only; comment votes and follower counts (final-time) are not used; featured_at is not used; account verified/prominent flags are fetch-time (mild late read; u_ver/u_prom). Source limit: the page query returns the top 50 threads by votes (page2 = 51-100 for some), so early low-vote threads on very busy launches can be missing (counts biased low for those, not leaky).
LM = honest pre-launch OOF prediction (the 00:05 live LM only exists from Oct 25).
