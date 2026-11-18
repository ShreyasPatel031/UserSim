# Pre-reveal forecast from comments (hours 0-4 PT), backtest

Days: 238 launch days (2026-03-01 to 2026-10-24) with >= 80% of the ranked line-up in the comment dump and an honest pre-launch LM prediction; 102,128 comments on 6,490 launch pages. Scored months: all but the first (month-forward training).

| cut (PT) | scorer | top 3 | top 5 | top 10 | Spearman | days |
|---|---|---|---|---|---|---|
| 00:00+1h | LM only | 58.3 [55, 62] | 68.1 [65, 71] | 74.9 [73, 77] | 63.1 [60, 66] | 207 |
| 00:00+1h | comment count only | 53.5 [50, 57] | 62.3 [60, 65] | 71.6 [70, 74] | 55.2 [52, 58] | 207 |
| | _minus LM_ | -4.8 [-9, -0] | -5.8 [-8, -3] | -3.3 [-5, -2] | -7.9 [-11, -5] | |
| 00:00+1h | combiner (LightGBM) | 61.5 [59, 64] | 67.1 [64, 70] | 74.8 [73, 77] | 60.9 [58, 64] | 207 |
| | _minus LM_ | +3.2 [+0, +6] | -1.0 [-3, +1] | -0.1 [-1, +1] | -2.2 [-4, -1] | |
| 00:00+1h | combiner (ridge) | 64.6 [62, 68] | 70.4 [68, 73] | 76.1 [74, 78] | 66.2 [64, 68] | 207 |
| | _minus LM_ | +6.3 [+3, +9] | +2.3 [+0, +4] | +1.2 [+0, +2] | +3.0 [+2, +4] | |
| 00:00+1h | ablation: ridge, LM features only | 58.3 [55, 62] | 68.1 [65, 71] | 74.9 [73, 77] | 63.1 [61, 66] | 207 |
| | _minus LM_ | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | |
| 00:00+1h | ablation: ridge, no account flags | 64.6 [62, 68] | 70.9 [69, 73] | 76.2 [74, 78] | 66.3 [64, 68] | 207 |
| | _minus LM_ | +6.3 [+3, +9] | +2.8 [+1, +5] | +1.3 [+0, +2] | +3.1 [+2, +4] | |
| 00:00+2h | LM only | 58.3 [55, 62] | 68.1 [65, 71] | 74.9 [73, 77] | 63.1 [61, 66] | 207 |
| 00:00+2h | comment count only | 55.7 [52, 59] | 63.6 [61, 66] | 70.3 [68, 72] | 55.4 [53, 58] | 207 |
| | _minus LM_ | -2.6 [-7, +2] | -4.5 [-8, -1] | -4.6 [-6, -3] | -7.7 [-11, -5] | |
| 00:00+2h | combiner (LightGBM) | 64.1 [61, 67] | 70.2 [68, 73] | 76.4 [74, 78] | 64.6 [62, 67] | 207 |
| | _minus LM_ | +5.8 [+3, +9] | +2.1 [+0, +4] | +1.4 [+0, +2] | +1.5 [-0, +3] | |
| 00:00+2h | combiner (ridge) | 66.3 [63, 70] | 71.9 [69, 74] | 77.0 [75, 79] | 68.4 [66, 71] | 207 |
| | _minus LM_ | +8.1 [+5, +12] | +3.8 [+2, +6] | +2.0 [+1, +3] | +5.3 [+4, +7] | |
| 00:00+2h | ablation: ridge, LM features only | 58.3 [55, 62] | 68.1 [65, 71] | 74.9 [73, 77] | 63.1 [60, 66] | 207 |
| | _minus LM_ | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | |
| 00:00+2h | ablation: ridge, no account flags | 66.8 [63, 70] | 72.2 [70, 75] | 76.9 [75, 79] | 68.3 [66, 70] | 207 |
| | _minus LM_ | +8.5 [+5, +12] | +4.1 [+2, +6] | +2.0 [+1, +3] | +5.1 [+4, +7] | |
| 00:00+3h | LM only | 58.3 [55, 62] | 68.1 [65, 71] | 74.9 [73, 77] | 63.1 [60, 66] | 207 |
| 00:00+3h | comment count only | 56.2 [53, 60] | 64.2 [61, 67] | 69.9 [68, 72] | 54.4 [51, 57] | 207 |
| | _minus LM_ | -2.1 [-7, +3] | -4.0 [-7, -1] | -5.0 [-7, -3] | -8.8 [-12, -6] | |
| 00:00+3h | combiner (LightGBM) | 63.6 [61, 66] | 70.3 [68, 73] | 76.2 [74, 78] | 65.0 [63, 67] | 207 |
| | _minus LM_ | +5.3 [+2, +9] | +2.2 [+0, +4] | +1.3 [+0, +2] | +1.9 [-0, +4] | |
| 00:00+3h | combiner (ridge) | 67.8 [65, 71] | 72.1 [70, 74] | 77.4 [76, 79] | 69.1 [67, 71] | 207 |
| | _minus LM_ | +9.5 [+6, +13] | +4.0 [+2, +6] | +2.5 [+2, +4] | +5.9 [+4, +8] | |
| 00:00+3h | ablation: ridge, LM features only | 58.3 [55, 62] | 68.1 [66, 71] | 74.9 [73, 77] | 63.1 [60, 66] | 207 |
| | _minus LM_ | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | |
| 00:00+3h | ablation: ridge, no account flags | 67.3 [64, 70] | 72.1 [70, 75] | 77.1 [75, 79] | 68.7 [66, 71] | 207 |
| | _minus LM_ | +9.0 [+6, +13] | +4.0 [+2, +6] | +2.2 [+1, +3] | +5.6 [+4, +7] | |
| 00:00+4h | LM only | 58.3 [55, 62] | 68.1 [65, 71] | 74.9 [73, 77] | 63.1 [60, 66] | 207 |
| 00:00+4h | comment count only | 58.0 [55, 61] | 64.6 [62, 67] | 69.7 [68, 72] | 54.1 [51, 57] | 207 |
| | _minus LM_ | -0.3 [-5, +4] | -3.5 [-7, -0] | -5.3 [-7, -4] | -9.1 [-12, -6] | |
| 00:00+4h | combiner (LightGBM) | 63.6 [61, 66] | 69.4 [67, 72] | 76.4 [75, 78] | 65.2 [63, 68] | 207 |
| | _minus LM_ | +5.3 [+2, +9] | +1.3 [-1, +4] | +1.5 [+0, +3] | +2.1 [-0, +4] | |
| 00:00+4h | combiner (ridge) | 66.8 [64, 70] | 72.5 [70, 75] | 77.6 [76, 79] | 69.5 [67, 72] | 207 |
| | _minus LM_ | +8.5 [+5, +12] | +4.3 [+2, +7] | +2.7 [+2, +4] | +6.3 [+4, +8] | |
| 00:00+4h | ablation: ridge, LM features only | 58.3 [55, 62] | 68.1 [65, 71] | 74.9 [73, 77] | 63.1 [60, 66] | 207 |
| | _minus LM_ | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | +0.0 [+0, +0] | |
| 00:00+4h | ablation: ridge, no account flags | 66.8 [64, 70] | 72.9 [70, 75] | 77.4 [76, 79] | 69.0 [67, 71] | 207 |
| | _minus LM_ | +8.5 [+5, +12] | +4.7 [+3, +7] | +2.5 [+1, +4] | +5.8 [+4, +8] | |

Comments per launch by cut: +1h mean 2.1, 7% with none; +2h mean 3.1, 6% with none; +3h mean 4.1, 6% with none; +4h mean 4.9, 5% with none

Leak checks: features use created_at <= T only; comment votes and follower counts (final-time) are not used; featured_at is not used; account verified/prominent flags are fetch-time (mild late read; u_ver/u_prom). Source limit: the page query returns the top 50 threads by votes (page2 = 51-100 for some), so early low-vote threads on very busy launches can be missing (counts biased low for those, not leaky).
LM = honest pre-launch OOF prediction (the 00:05 live LM only exists from Oct 25).
