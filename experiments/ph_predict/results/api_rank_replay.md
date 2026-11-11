# Pre-reveal API rank replay (orchestrator 21:05Z Nov 11)

**Field.** `daily_rank_at_fetch` in live/posts_ts.jsonl is the official API's own `post.dailyRank`. The raw snapshots
(../snapshots/<ts>_api.jsonl) carry `.dailyRank` next to `.votesCount` = 0 and `.latestScore` = 0, so it is not derived
by the capture. It is populated from the first snapshot after launch: 00:01 PT on Nov 8, 9 and 10, and 00:15 PT on
Nov 4.

**Days.** The 4 days whose capture starts before 01:00 PT: Nov 4, 8, 9 and 10. All other days' live capture starts
after the reveal.

**Method.** At each cut, rank by the latest dailyRank fetched by T (fetched_at <= T, no look-ahead), scored against
the final daily rank (top-k overlap). The rank moves between snapshots on every day, including Nov 8, so it is not
stale. Nov 8's early leaders simply did not hold.

Mean over the 4 days (top 3 / 5 / 10):

| cut (PT) | API rank | 00:05 LM |
|---|---|---|
| 01:00 | 41.7 / 55 / 65 | 41.7 / 55 / 72.5 |
| 01:15 | 66.7 / 60 / 70 | same |
| 02:00 | 66.7 / 65 / 75 | same |
| 03:00 | 58.3 / 65 / 77.5 | same |
| 03:30 | 58.3 / 80 / 80 | same |
| 04:00 | 58.3 / 75 / 82.5 | same |

Every 15-min cut is in api_rank_replay.json.

**3-day comparison.** On the days with comments_ts (Nov 4, 8, 10; Nov 9 has none), at the whole hours:

| cut (PT) | API rank | LM | comment ridge | blend (mean of rank positions) |
|---|---|---|---|---|
| 01:00 | 33.3 / 46.7 / 63.3 | 44.4 / 60 / 73.3 | 44.4 / 66.7 / 76.7 | 55.6 / 66.7 / 76.7 |
| 02:00 | 55.6 / 60 / 76.7 | same | 44.4 / 66.7 / 76.7 | 55.6 / 73.3 / 80 |
| 03:00 | 55.6 / 60 / 76.7 | same | 44.4 / 66.7 / 76.7 | 55.6 / 73.3 / 83.3 |
| 04:00 | 55.6 / 73.3 / 83.3 | same | 44.4 / 66.7 / 80 | **66.7 / 73.3 / 86.7** |

Treat this as a lead, not a result: n = 3–4 days, so there are no intervals.

**Live.** From Nov 12, comment_forecast.py live writes three ranks per point P1–P4: pred_rank (comment ridge),
pred_rank_api and pred_rank_blend. All three accrue forward side by side.
