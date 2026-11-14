# Pre-reveal lines on every replay day with hidden ranks (orchestrator 21:00Z Nov 13)
CLEAN_PRIOR = results/today_replay_fixed.parquet:clean_nosite

Days (11): 11-02, 11-03, 11-04, 11-05, 11-06, 11-07, 11-08, 11-09, 11-10, 11-11, 11-12; new vs the 7-day freeze (4): 11-05, 11-06, 11-07, 11-12. Frozen weights (fit on the 7 old days) -> the new days are out-of-sample. Label = dailyRank. Diff = shadow minus the published line at that point, paired, day bootstrap 95%.

Day sources: 11-02 vote_snapshots; 11-03 vote_snapshots; 11-04 posts_ts; 11-05 vote_snapshots no-comments clean stand-in (clean-with-site 00:05 or month-fold clean_nosite); 11-06 vote_snapshots clean stand-in (clean-with-site 00:05 or month-fold clean_nosite); 11-07 vote_snapshots clean stand-in (clean-with-site 00:05 or month-fold clean_nosite); 11-08 posts_ts; 11-09 posts_ts no-comments; 11-10 posts_ts; 11-11 posts_ts; 11-12 posts_ts clean stand-in (clean-with-site 00:05 or month-fold clean_nosite)

| point | line | days | top 3 | top 5 | top 10 | diff vs published, all days (t3 / t5 / t10) | new days only: diff (t3 / t5 / t10) |
|---|---|---|---|---|---|---|---|
| P1 | hr | 11 | 60.6 | 52.7 | 60.9 | -9.1 [-24.2, +6.1] / -14.5 [-25.5, -3.6] / -14.5 [-19.1, -10.0] | +0.0 / -15.0 / -10.0 (4) |
| P1 | hr_clean (published) | 11 | 69.7 | 67.3 | 75.5 | - | - (4) |
| P1 | best_cnosite | 11 | 63.6 | 63.6 | 72.7 | -6.1 [-15.2, +0.0] / -3.6 [-10.9, +3.6] / -2.7 [-6.4, +0.9] | -8.3 / -5.0 / -2.5 (4) |
| P1 | hybrid | 11 | 60.6 | 52.7 | 77.3 | -9.1 [-24.2, +6.1] / -14.5 [-25.5, -3.6] / +1.8 [+0.0, +4.5] | +0.0 / -15.0 / +2.5 (4) |
| P1 | hr_clean_arm2 | 11 | 72.7 | 67.3 | 75.5 | +3.0 [+0.0, +9.1] / +0.0 [-5.5, +5.5] / +0.0 [-2.7, +2.7] | +0.0 / +0.0 / +0.0 (4) |
| P1 | best_cnosite_arm2 | 11 | 63.6 | 63.6 | 70.9 | -6.1 [-15.2, +0.0] / -3.6 [-10.9, +3.6] / -4.5 [-8.2, -0.9] | -8.3 / -5.0 / +0.0 (4) |
| P1 | hybrid_arm2 | 11 | 60.6 | 52.7 | 77.3 | -9.1 [-24.2, +6.1] / -14.5 [-25.5, -3.6] / +1.8 [+0.0, +4.5] | +0.0 / -15.0 / +2.5 (4) |
| P2 | hr | 11 | 69.7 | 63.6 | 68.2 | -6.1 [-18.2, +6.1] / -9.1 [-14.5, -3.6] / -7.3 [-11.8, -2.7] | -8.3 / -10.0 / -5.0 (4) |
| P2 | hr_clean (published) | 11 | 75.8 | 72.7 | 75.5 | - | - (4) |
| P2 | best_cnosite | 11 | 69.7 | 70.9 | 69.1 | -6.1 [-15.2, +0.0] / -1.8 [-5.5, +0.0] / -6.4 [-10.0, -2.7] | -8.3 / -5.0 / -5.0 (4) |
| P2 | hybrid | 11 | 69.7 | 63.6 | 75.5 | -6.1 [-18.2, +6.1] / -9.1 [-14.5, -3.6] / +0.0 [+0.0, +0.0] | -8.3 / -10.0 / +0.0 (4) |
| P2 | hr_clean_arm2 | 11 | 75.8 | 72.7 | 74.5 | +0.0 [+0.0, +0.0] / +0.0 [-5.5, +5.5] / -0.9 [-3.6, +1.8] | +0.0 / +0.0 / +0.0 (4) |
| P2 | best_cnosite_arm2 | 11 | 72.7 | 72.7 | 69.1 | -3.0 [-9.1, +0.0] / +0.0 [-5.5, +5.5] / -6.4 [-10.0, -2.7] | +0.0 / -5.0 / -5.0 (4) |
| P2 | hybrid_arm2 | 11 | 69.7 | 63.6 | 73.6 | -6.1 [-18.2, +6.1] / -9.1 [-14.5, -3.6] / -1.8 [-6.4, +1.8] | -8.3 / -10.0 / +0.0 (4) |
| P3 | hr | 11 | 72.7 | 70.9 | 72.7 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / -6.4 [-10.0, -2.7] | +0.0 / +0.0 / -5.0 (4) |
| P3 | hr_clean | 11 | 75.8 | 72.7 | 79.1 | +3.0 [-6.1, +12.1] / +1.8 [-3.6, +7.3] / +0.0 [+0.0, +0.0] | +8.3 / +0.0 / +0.0 (4) |
| P3 | best_cnosite | 11 | 75.8 | 69.1 | 72.7 | +3.0 [-6.1, +15.2] / -1.8 [-7.3, +3.6] / -6.4 [-9.1, -3.6] | +8.3 / +0.0 / -5.0 (4) |
| P3 | hybrid (published) | 11 | 72.7 | 70.9 | 79.1 | - | - (4) |
| P3 | hr_clean_arm2 | 11 | 75.8 | 72.7 | 77.3 | +3.0 [-6.1, +12.1] / +1.8 [-3.6, +7.3] / -1.8 [-4.5, +0.0] | +8.3 / +0.0 / -2.5 (4) |
| P3 | best_cnosite_arm2 | 11 | 75.8 | 69.1 | 72.7 | +3.0 [-6.1, +12.1] / -1.8 [-5.5, +0.0] / -6.4 [-9.1, -3.6] | +8.3 / +0.0 / -2.5 (4) |
| P3 | hybrid_arm2 | 11 | 72.7 | 70.9 | 77.3 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / -1.8 [-4.5, +0.0] | +0.0 / +0.0 / -2.5 (4) |
| P345 | hr | 11 | 72.7 | 76.4 | 74.5 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / -3.6 [-7.3, +0.0] | +0.0 / +0.0 / -2.5 (4) |
| P345 | hr_clean | 11 | 72.7 | 74.5 | 78.2 | +0.0 [-9.1, +9.1] / -1.8 [-5.5, +0.0] / +0.0 [+0.0, +0.0] | +0.0 / +0.0 / +0.0 (4) |
| P345 | best_cnosite | 11 | 78.8 | 72.7 | 75.5 | +6.1 [-6.1, +18.2] / -3.6 [-9.1, +0.0] / -2.7 [-5.5, +0.0] | +8.3 / +0.0 / -2.5 (4) |
| P345 | hybrid (published) | 11 | 72.7 | 76.4 | 78.2 | - | - (4) |
| P345 | hr_clean_arm2 | 11 | 75.8 | 74.5 | 79.1 | +3.0 [-6.1, +12.1] / -1.8 [-5.5, +0.0] / +0.9 [+0.0, +2.7] | +8.3 / +0.0 / +0.0 (4) |
| P345 | best_cnosite_arm2 | 11 | 75.8 | 74.5 | 76.4 | +3.0 [-6.1, +12.1] / -1.8 [-5.5, +0.0] / -1.8 [-5.5, +1.8] | +8.3 / +0.0 / +0.0 (4) |
| P345 | hybrid_arm2 | 11 | 72.7 | 76.4 | 79.1 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +0.9 [+0.0, +2.7] | +0.0 / +0.0 / +0.0 (4) |

## Leave-one-day-out hr_clean vs the plain hidden rank (orchestrator 00:10Z Nov 14; weights refit without the test day)

| point | line | days | top 3 | top 5 | top 10 | minus plain hidden rank (t3 / t5 / t10) |
|---|---|---|---|---|---|---|
| P1 | plain hidden rank | 11 | 60.6 | 52.7 | 60.9 | - |
| P1 | hr_clean, LODO weights | 11 | 72.7 | 67.3 | 74.5 | +12.1 [+0.0, +24.2] / +14.5 [+3.6, +25.5] / +13.6 [+8.2, +19.1] |
| P1 | hybrid (hidden top 5 + LODO hr_clean) | 11 | 60.6 | 52.7 | 76.4 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +15.5 [+9.1, +20.9] |
| P2 | plain hidden rank | 11 | 69.7 | 63.6 | 68.2 | - |
| P2 | hr_clean, LODO weights | 11 | 75.8 | 72.7 | 75.5 | +6.1 [-6.1, +18.2] / +9.1 [+3.6, +14.5] / +7.3 [+1.8, +12.7] |
| P2 | hybrid (hidden top 5 + LODO hr_clean) | 11 | 69.7 | 63.6 | 75.5 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +7.3 [+2.7, +12.7] |
| P3 | plain hidden rank | 11 | 72.7 | 70.9 | 72.7 | - |
| P3 | hr_clean, LODO weights | 11 | 75.8 | 70.9 | 80.0 | +3.0 [-6.1, +12.1] / +0.0 [-5.5, +5.5] / +7.3 [+4.5, +10.0] |
| P3 | hybrid (hidden top 5 + LODO hr_clean) | 11 | 72.7 | 70.9 | 80.0 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +7.3 [+4.5, +10.0] |
| P345 | plain hidden rank | 11 | 72.7 | 76.4 | 74.5 | - |
| P345 | hr_clean, LODO weights | 11 | 72.7 | 74.5 | 79.1 | +0.0 [-9.1, +9.1] / -1.8 [-5.5, +0.0] / +4.5 [+0.9, +8.2] |
| P345 | hybrid (hidden top 5 + LODO hr_clean) | 11 | 72.7 | 76.4 | 79.1 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +4.5 [+0.9, +8.2] |

## Rule-5 check (all days interval > 0 AND same sign on the new days; top 3 not worse)

- P1 hybrid top 10: +1.8 [+0.0, +4.5]; at this effect ~18 days total for the interval to clear 0 (~7 more)
- P1 hr_clean_arm2 top 3: +3.0 [+0.0, +9.1]; at this effect ~25 days total for the interval to clear 0 (~14 more)
- P1 hybrid_arm2 top 10: +1.8 [+0.0, +4.5]; at this effect ~18 days total for the interval to clear 0 (~7 more)
- P3 hr_clean top 3: +3.0 [-6.1, +12.1]; at this effect ~99 days total for the interval to clear 0 (~88 more)
- P3 hr_clean top 5: +1.8 [-3.6, +7.3]; at this effect ~99 days total for the interval to clear 0 (~88 more)
- P3 best_cnosite top 3: +3.0 [-6.1, +15.2]; at this effect ~135 days total for the interval to clear 0 (~124 more)
- P3 hr_clean_arm2 top 3: +3.0 [-6.1, +12.1]; at this effect ~99 days total for the interval to clear 0 (~88 more)
- P3 hr_clean_arm2 top 5: +1.8 [-3.6, +7.3]; at this effect ~99 days total for the interval to clear 0 (~88 more)
- P3 best_cnosite_arm2 top 3: +3.0 [-6.1, +12.1]; at this effect ~99 days total for the interval to clear 0 (~88 more)
- P345 best_cnosite top 3: +6.1 [-6.1, +18.2]; at this effect ~44 days total for the interval to clear 0 (~33 more)
- P345 hr_clean_arm2 top 3: +3.0 [-6.1, +12.1]; at this effect ~99 days total for the interval to clear 0 (~88 more)
- P345 hr_clean_arm2 top 10: +0.9 [+0.0, +2.7]; at this effect ~25 days total for the interval to clear 0 (~14 more)
- P345 best_cnosite_arm2 top 3: +3.0 [-6.1, +12.1]; at this effect ~99 days total for the interval to clear 0 (~88 more)
- P345 hybrid_arm2 top 10: +0.9 [+0.0, +2.7]; at this effect ~25 days total for the interval to clear 0 (~14 more)
