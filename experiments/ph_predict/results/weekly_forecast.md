# Weekly forecast (PH weekly top 3/5/10), backtest

Truth = Product Hunt's official weekly_rank field (all scores below use it), weeks Monday 00:00 - Sunday 23:59 PT. It equals the order of total votes at the week's close (Sunday 23:59 PT), frozen afterwards; later votes include post-close growth (within-week Spearman of weekly_rank with final votes 0.99; W-SUN boundaries fit best). Complete weeks held: 44 (Jan 5 - Nov 8). Scored month-forward: 40 weeks (2026-02-02 .. 2026-11-08).

Inputs at the end of day k (23:59 PT): final daily rank (fixed at day end), day of week, line-up size, honest pre-launch LM (OOF, Mar-Oct; median-filled before), comments and unique commenters created by the launch day's end. No final votes.

## End-of-week call (Sunday 23:59 PT), vs final weekly top k

| scorer | top 3 | top 5 | top 10 |
|---|---|---|---|
| (b) daily rank + day of week | 57.5 [51, 65] | 71.5 [68, 75] | 77.8 [74, 80] |
| (c) ridge | 57.5 [52, 63] | 70.0 [66, 74] | 78.0 [75, 81] |
| (c) LightGBM | 59.2 [52, 66] | 65.0 [61, 69] | 75.5 [73, 78] |
| daily rank only | 13.3 [8, 19] | 43.0 [39, 47] | 61.2 [58, 64] |

## By day of the week: (i) vs final weekly top k among launches so far; (ii) vs the whole week's final top k; (reach = share of the whole week's top k already launched)

| end of | scorer | (i) top 3 / 5 / 10 | (ii) top 3 / 5 / 10 | reach 3 / 5 / 10 |
|---|---|---|---|---|
| Mon | (b) daily rank + day of week | 93 / 98 / 97 | 17 / 18 / 18 | 17 / 18 / 18 |
| Mon | (c) ridge | 93 / 98 / 96 | 17 / 18 / 18 | 17 / 18 / 18 |
| Tue | (b) daily rank + day of week | 84 / 87 / 96 | 37 / 40 / 38 | 39 / 41 / 38 |
| Tue | (c) ridge | 85 / 90 / 93 | 38 / 40 / 38 | 39 / 41 / 38 |
| Wed | (b) daily rank + day of week | 80 / 82 / 88 | 59 / 62 / 57 | 68 / 66 / 58 |
| Wed | (c) ridge | 79 / 84 / 92 | 58 / 64 / 58 | 68 / 66 / 58 |
| Thu | (b) daily rank + day of week | 64 / 76 / 87 | 58 / 68 / 72 | 86 / 84 / 76 |
| Thu | (c) ridge | 64 / 76 / 86 | 57 / 68 / 71 | 86 / 84 / 76 |
| Fri | (b) daily rank + day of week | 59 / 73 / 84 | 58 / 71 / 78 | 96 / 96 / 89 |
| Fri | (c) ridge | 58 / 74 / 84 | 58 / 72 / 78 | 96 / 96 / 89 |
| Sat | (b) daily rank + day of week | 59 / 72 / 82 | 58 / 71 / 79 | 98 / 98 / 96 |
| Sat | (c) ridge | 58 / 72 / 83 | 58 / 72 / 80 | 98 / 98 / 96 |
| Sun | (b) daily rank + day of week | 58 / 72 / 78 | 58 / 72 / 78 | 100 / 100 / 100 |
| Sun | (c) ridge | 58 / 70 / 78 | 58 / 70 / 78 | 100 / 100 / 100 |

Paired, end of week, ridge - (b): top 3 -0.0 [-8, +7], top 5 -1.5 [-4, +0], top 10 +0.2 [-2, +2]

## (a) Day-end votes (dated only from Oct 31; vote_snapshots)

- week 2026-10-26/2026-11-01 (2 days, 41 launches): day-end votes 100/100/80; daily rank 67/80/90; final votes (oracle) 100/100/90
- week 2026-11-02/2026-11-08 (6 days, 186 launches): day-end votes 100/80/90; daily rank 0/60/60; final votes (oracle) 100/100/90

Week Nov 2-8 is missing Nov 5 in vote_snapshots. Post-day growth over Oct 31 - Nov 8, final / day-end votes:
- median 1.035 (p90 1.17) across all launches;
- median 1.21 for the final weekly top 10, so the winners keep growing after their day;
- within-week Spearman of day-end vs final votes is 0.99 (186 launches), so the order barely changes.

Dated day-end votes are the strongest weekly input. They exist only from Oct 31 (warehouse vote_snapshots and live
posts_ts), so they need forward accrual rather than a historical backtest.

## Why the early replay's weekly 44 / 50 / 62 (results/early_forecast_replay.json, period_lists_at_R2)

That replay scored 6 days (Nov 2, 3, 4, 8, 9, 10). At each day's R0+2h it took final votes for the week's earlier days
and the R0+2h projection for the day itself.

| loss (top 3 / 5 / 10, points) | source |
|---|---|
| 22 / 30 / 35 | weekly top-k launches from later days of the week, not yet launched (reachable 78 / 70 / 65) |
| 33 / 20 / 3 | ordering among the reachable launches, almost all from the same day's 2-hour projection (earlier days used final votes) |
| 0 | post-day vote growth: earlier days used final votes, a leak in that replay's favour; honestly it costs about 0 / 20 / 0 on the one week with day-end votes |
| 0 | featuring: every launch in the table is featured (daily-ranked), so there is no featuring effect in this data |

The Nov 9 and Nov 10 rows were also scored against an unfinished week, using weekly_rank as of Nov 11.
