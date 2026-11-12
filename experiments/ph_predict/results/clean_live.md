# Clean 00:05 model on the live days (clean_live.py, Nov 12)

Product Hunt names the day's #1 launch's makers only after the day, so every input that needs a maker to be NAMED is leaky in
rows read after the day; the deployed model is trained on those values and served 00:05 values. Same frame as parity_live
(features.build + llm), daily expanding refit (deployed cadence), 00:05 test rows, LIVE_PARAMS, 5 seeds. Truth = official
daily_rank. Paired differences vs the deployed configuration, 95% day bootstrap.

| variant | 14 live days: top 3 / 5 / 10 | #1 / #2 / #3 pick in top 3 | exact winner | top 3 minus deployed | 8 on-time days: top 3 / 5 / 10 | #1 in top 3 |
|---|---|---|---|---|---|---|
| deployed (all live sources) | 57.1 / 64.3 / 76.4 | 7 / 10 / 7 | 5 | - | 50.0 / 60.0 / 73.8 | 3 / 8 |
| no maker-profile inputs | 59.5 / 67.1 / 75.7 | 11 / 8 / 6 | 2 | +2.4 [+0.0, +7.1] | 54.2 / 65.0 / 75.0 | 7 / 8 |
| **clean_v3** (also no ph_n_makers_new, ph_maker_has_headline, x_any_verified, ph_self_hunted; maker count kept) | **61.9 / 67.1 / 76.4** | **11 / 8 / 7** | 3 | **+4.8 [+0.0, +11.9]** | **58.3 / 67.5 / 75.0** | 7 / 8 |
| clean_v3 + any named maker (min(named, 1), same in train and serve) | 57.1 / 70.0 / 75.7 | 12 / 7 / 5 | 2 | +0.0 [-9.5, +9.5] | 58.3 / 67.5 / 73.8 | 7 / 8 |
| published (the forecasts table, first run per day) | 52.4 / 65.7 / 77.9 | 7 / 10 / 5 | 3 | -4.8 [-14.3, +4.8] | 45.8 / 62.5 / 73.8 | 4 / 8 |

clean_v3 is never worse than deployed on top 3 (interval lower bound 0). It is the 00:05 shadow line `clean` from Nov 12
(makerfix_shadow.py rank_clean, after 01:00 PT from 00:05 inputs), scored beside published and makerfix.

Pre-reveal recipe with the clean model as the LM prior (pred_rank_best_clean; best_clean_replay.json, 6 replay days, hourly
API ranks; weights were tuned with the published LM):

| point | published LM: LM only / best | clean LM: LM only / best |
|---|---|---|
| P1 | 38.9 / 66.7 (top 3) | 55.6 / 72.2 |
| P2 | 38.9 / 72.2 | 55.6 / 66.7 |
| P3 | 38.9 / 83.3 | 55.6 / 77.8 |

The clean model alone beats the published LM by 17 points top 3 on these 6 days; combined with the hidden rank it helps at
P1 and is slightly behind at P2 / P3. Recorded as pred_rank_best_clean in the P files, scored forward; pred_rank_best unchanged.
