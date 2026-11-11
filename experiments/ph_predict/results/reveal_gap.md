# Reveal-time gap (live 15-min API snapshots)

Days: 2026-11-04, 2026-11-08, 2026-11-09, 2026-11-10.

| day | R0 (PT) | shown >0 at R0 | hide flag at R0 | missing at R0 (top-10 among them) | votes-order vs final rank, top 3/5/10 |
|---|---|---|---|---|---|
| 2026-11-04 | 04:00 | 1.00 | 1.00 | 0 (0) | 100 / 100 / 100 |
| 2026-11-08 | 04:00 | 1.00 | 1.00 | 0 (0) | 100 / 80 / 100 |
| 2026-11-09 | 04:00 | 1.00 | 0.96 | 0 (0) | 100 / 80 / 100 |
| 2026-11-10 | 04:00 | 1.00 | 0.90 | 0 (0) | 100 / 100 / 100 |

Raw votes at R0 + offset, mean over the days, top 3 / 5 / 10 (vs final daily rank; vs final votes):

| offset | vs final rank | vs final votes | share of line-up still at 0 |
|---|---|---|---|
| +0 min | 58.3 / 70.0 / 82.5 | 58.3 / 65.0 / 82.5 | 0.00 |
| +15 min | 75.0 / 80.0 / 87.5 | 75.0 / 75.0 / 87.5 | 0.00 |
| +30 min | 75.0 / 90.0 / 87.5 | 75.0 / 80.0 / 87.5 | 0.00 |
| +45 min | 75.0 / 90.0 / 87.5 | 75.0 / 80.0 / 87.5 | 0.00 |
| +60 min | 83.3 / 90.0 / 87.5 | 83.3 / 80.0 / 87.5 | 0.00 |
| +120 min | 83.3 / 90.0 / 90.0 | 83.3 / 80.0 / 90.0 | 0.00 |

## Reading

**(1) Timing.** The reveal is exactly 04:00 PT (12:00Z) on all 4 days. At that snapshot 100% of launches already show votes (hide flags still set on 90–100% of rows), so it's not a partial or stale read. But votes keep reordering fast in the first hour:

| raw votes at | top 3 | top 5 | top 10 |
|---|---|---|---|
| reveal | 58 | 70 | 82 |
| +15 min | 75 | 80 | 88 |
| +30 min | 75 | 90 | 88 |
| +60 min | 83 | 90 | 88 |
| +2 h | 83 | 90 | 90 |

E5's 04:00–05:00 PT Wayback bucket (85 / 93 / 92) averages captures across that hour, so it sits near our +30 to +60 min. **The gap is the minute within the hour, not a defect.**

**(2) Line-up.** No ranked launch is missing at R0 on any day, so no top-10 finisher is lost.

**(3) Truth.** The final top 3 by votes equals the final daily top 3 on all 4 days (top 5: 80–100). Scoring against votes instead of rank lowers top 5 slightly and leaves top 3 unchanged.

**(4) Day mix.** Only 4 days have 15-min reveal coverage (Nov 4, 8, 9, 10). These days' R0 is 58 vs the 6-day hourly replay's 72, so day mix matters at this n.

**Fix.** Two extra live points, R0q (reveal +15 min) and R0h (+30 min), in early_forecast.py POINTS. Both score forward next to R0 in the scoreboard and NORTH_STAR. R0 stays as it is.
