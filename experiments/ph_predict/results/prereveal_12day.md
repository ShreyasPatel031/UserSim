# Pre-reveal lines on every replay day with hidden ranks (orchestrator 21:00Z Nov 13)

Days (8): 11-02, 11-03, 11-04, 11-08, 11-09, 11-10, 11-11, 11-12; new vs the 7-day freeze (1): 11-12. Frozen weights (fit on the 7 old days) -> the new days are out-of-sample. Label = dailyRank. Diff = shadow minus the published line at that point, paired, day bootstrap 95%.

Day sources: 11-02 vote_snapshots; 11-03 vote_snapshots; 11-04 posts_ts; 11-08 posts_ts; 11-09 posts_ts no-comments; 11-10 posts_ts; 11-11 posts_ts; 11-12 posts_ts clean-with-site stand-in

| point | line | days | top 3 | top 5 | top 10 | diff vs published, all days (t3 / t5 / t10) | new days only: diff (t3 / t5 / t10) |
|---|---|---|---|---|---|---|---|
| P1 | hr | 8 | 62.5 | 55.0 | 65.0 | -8.3 [-25.0, +12.5] / -10.0 [-22.5, +2.5] / -16.2 [-23.8, -8.8] | +33.3 / +0.0 / -10.0 (1) |
| P1 | hr_clean (published) | 8 | 70.8 | 65.0 | 81.2 | - | - (1) |
| P1 | best_cnosite | 8 | 70.8 | 65.0 | 77.5 | +0.0 [-12.5, +12.5] / +0.0 [-7.5, +7.5] / -3.8 [-8.8, +1.2] | +0.0 / +0.0 / -10.0 (1) |
| P1 | hybrid | 8 | 62.5 | 55.0 | 81.2 | -8.3 [-25.0, +12.5] / -10.0 [-25.0, +2.5] / +0.0 [-3.8, +3.8] | +33.3 / +0.0 / +0.0 (1) |
| P1 | hr_clean_arm2 | 8 | 75.0 | 67.5 | 80.0 | +4.2 [+0.0, +12.5] / +2.5 [+0.0, +7.5] / -1.2 [-5.0, +2.5] | +0.0 / +0.0 / -10.0 (1) |
| P1 | best_cnosite_arm2 | 8 | 66.7 | 65.0 | 75.0 | -4.2 [-12.5, +0.0] / +0.0 [-7.5, +7.5] / -6.2 [-11.2, -1.2] | +0.0 / +0.0 / +0.0 (1) |
| P1 | hybrid_arm2 | 8 | 62.5 | 55.0 | 82.5 | -8.3 [-25.0, +12.5] / -10.0 [-25.0, +2.5] / +1.2 [-2.5, +5.0] | +33.3 / +0.0 / +0.0 (1) |
| P2 | hr | 8 | 70.8 | 67.5 | 73.8 | -0.0 [-16.7, +16.7] / -7.5 [-15.0, -2.5] / -6.2 [-12.5, +0.0] | -33.3 / +0.0 / +0.0 (1) |
| P2 | hr_clean (published) | 8 | 70.8 | 75.0 | 80.0 | - | - (1) |
| P2 | best_cnosite | 8 | 70.8 | 75.0 | 75.0 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / -5.0 [-8.8, -1.2] | +0.0 / +0.0 / +0.0 (1) |
| P2 | hybrid | 8 | 70.8 | 67.5 | 80.0 | -0.0 [-16.7, +16.7] / -7.5 [-15.0, -2.5] / +0.0 [+0.0, +0.0] | -33.3 / +0.0 / +0.0 (1) |
| P2 | hr_clean_arm2 | 8 | 79.2 | 75.0 | 80.0 | +8.3 [+0.0, +20.8] / +0.0 [-7.5, +7.5] / +0.0 [-3.8, +3.8] | +0.0 / +0.0 / +0.0 (1) |
| P2 | best_cnosite_arm2 | 8 | 75.0 | 77.5 | 75.0 | +4.2 [+0.0, +12.5] / +2.5 [+0.0, +7.5] / -5.0 [-8.8, -1.2] | +0.0 / +0.0 / +0.0 (1) |
| P2 | hybrid_arm2 | 8 | 70.8 | 67.5 | 78.8 | -0.0 [-16.7, +16.7] / -7.5 [-15.0, -2.5] / -1.2 [-5.0, +2.5] | -33.3 / +0.0 / +0.0 (1) |
| P3 | hr | 8 | 75.0 | 72.5 | 77.5 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / -6.2 [-8.8, -2.5] | +0.0 / +0.0 / +0.0 (1) |
| P3 | hr_clean | 8 | 79.2 | 75.0 | 83.8 | +4.2 [-8.3, +16.7] / +2.5 [-5.0, +10.0] / +0.0 [+0.0, +0.0] | +33.3 / +0.0 / +0.0 (1) |
| P3 | best_cnosite | 8 | 79.2 | 70.0 | 78.8 | +4.2 [-8.3, +16.7] / -2.5 [-10.0, +5.0] / -5.0 [-10.0, +0.0] | +33.3 / +0.0 / +10.0 (1) |
| P3 | hybrid (published) | 8 | 75.0 | 72.5 | 83.8 | - | - (1) |
| P3 | hr_clean_arm2 | 8 | 79.2 | 75.0 | 83.8 | +4.2 [-8.3, +16.7] / +2.5 [-5.0, +10.0] / +0.0 [-3.8, +3.8] | +33.3 / +0.0 / +10.0 (1) |
| P3 | best_cnosite_arm2 | 8 | 79.2 | 70.0 | 77.5 | +4.2 [-8.3, +16.7] / -2.5 [-7.5, +0.0] / -6.2 [-10.0, -1.2] | +33.3 / +0.0 / +10.0 (1) |
| P3 | hybrid_arm2 | 8 | 75.0 | 72.5 | 83.8 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +0.0 [-3.8, +3.8] | +0.0 / +0.0 / +10.0 (1) |
| P345 | hr | 8 | 75.0 | 80.0 | 80.0 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / -3.8 [-7.5, -1.2] | +0.0 / +0.0 / -10.0 (1) |
| P345 | hr_clean | 8 | 75.0 | 77.5 | 83.8 | +0.0 [-12.5, +12.5] / -2.5 [-7.5, +0.0] / +0.0 [+0.0, +0.0] | +0.0 / +0.0 / +0.0 (1) |
| P345 | best_cnosite | 8 | 79.2 | 75.0 | 81.2 | +4.2 [-8.3, +16.7] / -5.0 [-12.5, +0.0] / -2.5 [-6.2, +0.0] | +33.3 / +0.0 / +0.0 (1) |
| P345 | hybrid (published) | 8 | 75.0 | 80.0 | 83.8 | - | - (1) |
| P345 | hr_clean_arm2 | 8 | 79.2 | 77.5 | 86.2 | +4.2 [-8.3, +16.7] / -2.5 [-7.5, +0.0] / +2.5 [+0.0, +6.2] | +33.3 / +0.0 / +0.0 (1) |
| P345 | best_cnosite_arm2 | 8 | 79.2 | 77.5 | 82.5 | +4.2 [-8.3, +16.7] / -2.5 [-7.5, +0.0] / -1.2 [-3.8, +0.0] | +33.3 / +0.0 / +0.0 (1) |
| P345 | hybrid_arm2 | 8 | 75.0 | 80.0 | 86.2 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +2.5 [+0.0, +6.2] | +0.0 / +0.0 / +0.0 (1) |

## Rule-5 check (all days interval > 0 AND same sign on the new days; top 3 not worse)

- P1 hr_clean_arm2 top 3: +4.2 [+0.0, +12.5]; at this effect ~18 days total for the interval to clear 0 (~10 more)
- P1 hr_clean_arm2 top 5: +2.5 [+0.0, +7.5]; at this effect ~18 days total for the interval to clear 0 (~10 more)
- P1 hybrid_arm2 top 10: +1.2 [-2.5, +5.0]; at this effect ~72 days total for the interval to clear 0 (~64 more)
- P2 hr_clean_arm2 top 3: +8.3 [+0.0, +20.8]; at this effect ~13 days total for the interval to clear 0 (~5 more)
- P2 best_cnosite_arm2 top 3: +4.2 [+0.0, +12.5]; at this effect ~18 days total for the interval to clear 0 (~10 more)
- P2 best_cnosite_arm2 top 5: +2.5 [+0.0, +7.5]; at this effect ~18 days total for the interval to clear 0 (~10 more)
- P3 hr_clean top 3: +4.2 [-8.3, +16.7]; at this effect ~72 days total for the interval to clear 0 (~64 more)
- P3 hr_clean top 5: +2.5 [-5.0, +10.0]; at this effect ~72 days total for the interval to clear 0 (~64 more)
- P3 best_cnosite top 3: +4.2 [-8.3, +16.7]; at this effect ~72 days total for the interval to clear 0 (~64 more)
- P3 hr_clean_arm2 top 3: +4.2 [-8.3, +16.7]; at this effect ~72 days total for the interval to clear 0 (~64 more)
- P3 hr_clean_arm2 top 5: +2.5 [-5.0, +10.0]; at this effect ~72 days total for the interval to clear 0 (~64 more)
- P3 best_cnosite_arm2 top 3: +4.2 [-8.3, +16.7]; at this effect ~72 days total for the interval to clear 0 (~64 more)
- P345 best_cnosite top 3: +4.2 [-8.3, +16.7]; at this effect ~72 days total for the interval to clear 0 (~64 more)
- P345 hr_clean_arm2 top 3: +4.2 [-8.3, +16.7]; at this effect ~72 days total for the interval to clear 0 (~64 more)
- P345 hr_clean_arm2 top 10: +2.5 [+0.0, +6.2]; at this effect ~13 days total for the interval to clear 0 (~5 more)
- P345 best_cnosite_arm2 top 3: +4.2 [-8.3, +16.7]; at this effect ~72 days total for the interval to clear 0 (~64 more)
- P345 hybrid_arm2 top 10: +2.5 [+0.0, +6.2]; at this effect ~13 days total for the interval to clear 0 (~5 more)

## Verdict
No row qualifies; nothing deployed. Only 8 days have hidden ranks before 03:45 PT, not 12: rank_now covers 12 days, but on Oct 31, Nov 1, 6 and 7
the first read is at 06:00-07:00 PT, after the reveal. So there is 1 new out-of-sample day (Nov 12; its clean prior is the clean-with-site
stand-in because that shadow file predates the nosite column). Nov 13 becomes the 9th day once final.
Best lead: hr_clean with the arm-2 prior in place of clean_nosite: P1 top 3 +4.2 [+0.0, +12.5], P2 top 3 +8.3 [+0.0, +20.8]. It never loses a
day, but the lower bound only touches 0, and the single new day is a tie. At these effects it needs ~13-18 days in total (5-10 more).
At P3 / P345 the published hybrid is matched or beaten only within noise (needs ~70 days), except hybrid_arm2 / hr_clean_arm2 at P345 top 10
+2.5 [+0.0, +6.2] (~13 days).
