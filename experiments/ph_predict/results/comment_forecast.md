# Pre-reveal forecast from comments (hours 0-4 PT), backtest

Days: 238 launch days (2026-03-01 to 2026-10-24) with >= 80% of the ranked line-up in the comment dump and an honest pre-launch LM prediction; 102,128 comments on 6,490 launch pages. Scored months: all but the first (month-forward training).

| cut (PT) | scorer | top 3 | top 5 | top 10 | Spearman | days |
|---|---|---|---|---|---|---|
| 00:00+1h | LM only | 63.0 [60, 66] | 69.3 [67, 72] | 75.0 [73, 77] | 65.6 [63, 68] | 207 |
| 00:00+1h | comment count only | 54.3 [51, 57] | 62.5 [60, 65] | 71.4 [70, 73] | 56.1 [53, 59] | 207 |
| | _minus LM_ | -8.7 [-13, -4] | -6.8 [-10, -4] | -3.6 [-5, -2] | -9.5 [-12, -7] | |
| 00:00+1h | combiner (LightGBM) | 63.6 [60, 67] | 67.6 [65, 70] | 75.1 [73, 77] | 62.6 [60, 65] | 207 |
| | _minus LM_ | +0.6 [-2, +4] | -1.6 [-4, +0] | +0.1 [-1, +1] | -3.0 [-5, -1] | |
| 00:00+1h | combiner (ridge) | 66.2 [63, 69] | 70.8 [68, 73] | 76.4 [75, 78] | 67.6 [65, 70] | 207 |
| | _minus LM_ | +3.2 [+0, +6] | +1.5 [-0, +3] | +1.4 [+1, +2] | +2.0 [+1, +3] | |
| 00:00+1h | ablation: ridge, LM features only | 62.8 [60, 66] | 69.1 [66, 72] | 74.9 [73, 77] | 65.4 [63, 68] | 207 |
| | _minus LM_ | -0.2 [-0, +0] | -0.2 [-0, +0] | -0.0 [-0, +0] | -0.1 [-0, -0] | |
| 00:00+1h | ablation: ridge, no account flags | 66.7 [64, 70] | 71.2 [69, 74] | 76.4 [75, 78] | 67.7 [66, 70] | 207 |
| | _minus LM_ | +3.7 [+1, +6] | +1.9 [+0, +4] | +1.4 [+1, +2] | +2.1 [+1, +4] | |
| 00:00+2h | LM only | 63.0 [60, 66] | 69.3 [67, 72] | 75.0 [73, 77] | 65.6 [63, 68] | 207 |
| 00:00+2h | comment count only | 56.2 [53, 60] | 63.1 [61, 66] | 70.2 [68, 72] | 55.7 [53, 58] | 207 |
| | _minus LM_ | -6.8 [-11, -3] | -6.2 [-9, -3] | -4.7 [-6, -3] | -9.9 [-13, -7] | |
| 00:00+2h | combiner (LightGBM) | 64.9 [62, 68] | 68.5 [66, 71] | 75.7 [74, 77] | 64.8 [62, 67] | 207 |
| | _minus LM_ | +1.9 [-1, +5] | -0.8 [-3, +2] | +0.7 [-0, +2] | -0.8 [-3, +1] | |
| 00:00+2h | combiner (ridge) | 68.8 [66, 72] | 72.2 [70, 75] | 77.0 [75, 79] | 68.9 [67, 71] | 207 |
| | _minus LM_ | +5.8 [+3, +9] | +2.9 [+1, +5] | +2.0 [+1, +3] | +3.3 [+2, +5] | |
| 00:00+2h | ablation: ridge, LM features only | 62.8 [60, 66] | 69.1 [66, 72] | 74.9 [73, 77] | 65.4 [63, 68] | 207 |
| | _minus LM_ | -0.2 [-0, +0] | -0.2 [-0, +0] | -0.0 [-0, +0] | -0.1 [-0, -0] | |
| 00:00+2h | ablation: ridge, no account flags | 68.4 [65, 71] | 72.5 [70, 75] | 76.7 [75, 78] | 68.8 [67, 71] | 207 |
| | _minus LM_ | +5.5 [+2, +8] | +3.2 [+1, +5] | +1.7 [+1, +3] | +3.2 [+2, +5] | |
| 00:00+3h | LM only | 63.0 [60, 66] | 69.3 [67, 72] | 75.0 [73, 77] | 65.6 [63, 68] | 207 |
| 00:00+3h | comment count only | 56.5 [53, 60] | 64.0 [61, 67] | 69.7 [68, 72] | 54.5 [52, 57] | 207 |
| | _minus LM_ | -6.4 [-11, -2] | -5.3 [-8, -2] | -5.3 [-7, -4] | -11.0 [-14, -8] | |
| 00:00+3h | combiner (LightGBM) | 65.5 [63, 68] | 70.0 [68, 72] | 76.1 [74, 78] | 65.1 [63, 68] | 207 |
| | _minus LM_ | +2.6 [-0, +6] | +0.8 [-1, +3] | +1.1 [+0, +2] | -0.5 [-3, +2] | |
| 00:00+3h | combiner (ridge) | 69.4 [66, 72] | 73.4 [71, 76] | 76.9 [75, 78] | 69.2 [67, 71] | 207 |
| | _minus LM_ | +6.4 [+3, +10] | +4.2 [+2, +6] | +1.9 [+1, +3] | +3.6 [+2, +5] | |
| 00:00+3h | ablation: ridge, LM features only | 62.8 [60, 66] | 69.1 [67, 72] | 74.9 [73, 77] | 65.4 [63, 68] | 207 |
| | _minus LM_ | -0.2 [-0, +0] | -0.2 [-0, +0] | -0.0 [-0, +0] | -0.1 [-0, -0] | |
| 00:00+3h | ablation: ridge, no account flags | 69.6 [67, 72] | 73.3 [71, 76] | 76.7 [75, 78] | 69.2 [67, 71] | 207 |
| | _minus LM_ | +6.6 [+4, +10] | +4.1 [+2, +6] | +1.7 [+1, +3] | +3.6 [+2, +5] | |
| 00:00+4h | LM only | 63.0 [60, 66] | 69.3 [67, 72] | 75.0 [73, 77] | 65.6 [63, 68] | 207 |
| 00:00+4h | comment count only | 58.1 [55, 62] | 64.7 [62, 67] | 69.6 [68, 72] | 54.3 [52, 57] | 207 |
| | _minus LM_ | -4.8 [-9, -0] | -4.5 [-8, -2] | -5.4 [-7, -4] | -11.3 [-14, -8] | |
| 00:00+4h | combiner (LightGBM) | 65.4 [63, 68] | 69.8 [67, 72] | 76.5 [75, 78] | 66.5 [64, 69] | 207 |
| | _minus LM_ | +2.4 [-0, +5] | +0.5 [-2, +3] | +1.5 [+0, +3] | +1.0 [-1, +3] | |
| 00:00+4h | combiner (ridge) | 70.0 [67, 73] | 73.6 [71, 76] | 77.2 [76, 79] | 69.9 [68, 72] | 207 |
| | _minus LM_ | +7.1 [+4, +10] | +4.3 [+2, +6] | +2.3 [+1, +3] | +4.3 [+3, +6] | |
| 00:00+4h | ablation: ridge, LM features only | 62.8 [60, 66] | 69.1 [67, 72] | 74.9 [73, 77] | 65.4 [63, 68] | 207 |
| | _minus LM_ | -0.2 [-0, +0] | -0.2 [-0, +0] | -0.0 [-0, +0] | -0.1 [-0, -0] | |
| 00:00+4h | ablation: ridge, no account flags | 69.6 [67, 72] | 73.8 [71, 76] | 77.4 [76, 79] | 69.8 [68, 72] | 207 |
| | _minus LM_ | +6.6 [+3, +10] | +4.5 [+2, +6] | +2.4 [+1, +4] | +4.2 [+2, +6] | |

Comments per launch by cut: +1h mean 2.1, 7% with none; +2h mean 3.1, 6% with none; +3h mean 4.1, 6% with none; +4h mean 4.9, 5% with none

Leak checks: features use created_at <= T only; comment votes and follower counts (final-time) are not used; featured_at is not used; account verified/prominent flags are fetch-time (mild late read; u_ver/u_prom). Source limit: the page query returns the top 50 threads by votes (page2 = 51-100 for some), so early low-vote threads on very busy launches can be missing (counts biased low for those, not leaky).
LM = honest pre-launch OOF prediction (the 00:05 live LM only exists from Oct 25).

## Live-compatible model and live replay (added 21:40Z Nov 11)

Live model (`python comment_forecast.py fit` -> results/comment_forecast_live_model.json): ridge per cut on all 238 days,
LM as -log(within-day LM rank) (the live 00:05 LM is a rank only), no account flags (live comments carry none).
Month-forward backtest of this variant, minus LM only: +1h +3.2 / +1.0 / +0.8; +2h +4.8 / +1.9 / +1.1;
+3h +6.1 / +2.1 / +1.2; **+4h +5.0 [+2.3, +7.6] / +3.9 [+1.9, +5.7] / +2.0 [+0.9, +3.0]** (top 3 / 5 / 10).

Live replay (`CF_DRY=<dir> python comment_forecast.py live <day> P1..P4`, then comment_forecast_replay_score.py): the
5 days with live comments_ts, a 00:05 LM forecast and final ranks (Nov 2, 3, 4, 8, 10; Nov 8 has only 17/46 launches
with an LM score). Comments filtered by created_at <= T from the day's capture (not a strict as-of replay).

| point | LM only | comment count only | comment ridge |
|---|---|---|---|
| P1 (01:00 PT) | 40.0 / 64.0 / 78.0 | 46.7 / 64.0 / 64.0 | 46.7 / 68.0 / 78.0 |
| P4 (04:00 PT) | 40.0 / 64.0 / 78.0 | 40.0 / 64.0 / 74.0 | 46.7 / 68.0 / 80.0 |

Comments added to the vote forecast (raw votes z + w x z(P4 comment score)), same 5 days:
R0 w=0: 73.3 / 80 / 90; w=0.25: 73.3 / 84 / 90; w=0.5: 80 / 80 / 92; w=1: 66.7 / 80 / 90.
R1 w=0: 93.3 / 92 / 92; w=0.25: 93.3 / 88 / 92; w=0.5: 93.3 / 80 / 92. No consistent gain; not adopted (5 days).

Live data notes: live comments_ts / api_comments "username" is one constant per launch (not the commenter), so the live
identity is commenter_user_id; maker user ids come from the dump's username->id pairs (in memory), known for about 40%
of launches, so on the rest team comments count as outside comments (n_team low, u_out high vs training).
