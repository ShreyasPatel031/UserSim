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

## More days: the pipeline's own hourly reads and the 00:05 pull (Nov 12)

Sources checked:
- raw/ph_at_launch/<day>/snapshots: each folder's pre-reveal files are the PREVIOUS PT day's launches continuing (the folder is the UTC date), so Nov 3 / Nov 7 add nothing new.
- api_hourly / api_detail: start 00:01-01:31 PT only on days already covered (Nov 4, 8, 10, 11).
- warehouse vote_snapshots: rank_now = the official API dailyRank, read hourly from ~00:07 PT, also before the reveal.
- raw/daily/<d>/<d>.json: the pipeline's 00:05 pull with dailyRank.
Nothing else in the bucket carries a per-post rank read before 04:00 PT on its launch day.

### A. Hourly pre-reveal API rank (vote_snapshots), per day, top 3 / 5 / 10

| day | cut | read at (UTC) | API rank | LM | comment ridge | blend |
|---|---|---|---|---|---|---|
| 2026-11-02 | P1 | 09:00 | 67 / 40 / 80 | 33 / 80 / 90 | 33 / 80 / 80 | 67 / 80 / 90 |
| 2026-11-02 | P2 | 10:00 | 67 / 60 / 90 | 33 / 80 / 90 | 33 / 80 / 90 | 67 / 80 / 90 |
| 2026-11-02 | P3 | 11:00 | 100 / 80 / 90 | 33 / 80 / 90 | 33 / 80 / 90 | 67 / 80 / 90 |
| 2026-11-02 | P4 | 11:00 | 100 / 80 / 90 | 33 / 80 / 90 | 33 / 80 / 90 | 67 / 80 / 90 |
| 2026-11-03 | P1 | 09:00 | 100 / 60 / 60 | 33 / 60 / 80 | 67 / 60 / 80 | 67 / 60 / 60 |
| 2026-11-03 | P2 | 10:00 | 100 / 80 / 80 | 33 / 60 / 80 | 67 / 60 / 80 | 67 / 80 / 80 |
| 2026-11-03 | P3 | 11:00 | 100 / 80 / 90 | 33 / 60 / 80 | 67 / 60 / 80 | 100 / 80 / 90 |
| 2026-11-03 | P4 | 11:00 | 100 / 80 / 90 | 33 / 60 / 80 | 67 / 80 / 80 | 100 / 80 / 80 |
| 2026-11-04 | P1 | 09:00 | 67 / 60 / 60 | 33 / 40 / 80 | 33 / 60 / 90 | 100 / 60 / 80 |
| 2026-11-04 | P2 | 10:00 | 67 / 80 / 70 | 33 / 40 / 80 | 33 / 60 / 90 | 67 / 80 / 90 |
| 2026-11-04 | P3 | 11:00 | 67 / 80 / 90 | 33 / 40 / 80 | 33 / 60 / 90 | 100 / 60 / 90 |
| 2026-11-04 | P4 | 11:00 | 67 / 80 / 90 | 33 / 40 / 80 | 33 / 60 / 90 | 100 / 60 / 100 |
| 2026-11-08 | P1 | 09:00 | 33 / 40 / 70 | 67 / 60 / 80 | 67 / 60 / 80 | 33 / 80 / 80 |
| 2026-11-08 | P2 | 10:00 | 33 / 40 / 70 | 67 / 60 / 80 | 67 / 60 / 80 | 33 / 80 / 90 |
| 2026-11-08 | P3 | 11:00 | 33 / 80 / 60 | 67 / 60 / 80 | 67 / 60 / 80 | 33 / 80 / 80 |
| 2026-11-08 | P4 | 11:00 | 33 / 80 / 60 | 67 / 60 / 80 | 67 / 60 / 80 | 33 / 80 / 80 |
| 2026-11-09 | P1 | 09:00 | 100 / 80 / 70 | 33 / 40 / 70 | - | - |
| 2026-11-09 | P2 | 10:00 | 67 / 80 / 80 | 33 / 40 / 70 | - | - |
| 2026-11-09 | P3 | 11:00 | 67 / 80 / 80 | 33 / 40 / 70 | - | - |
| 2026-11-09 | P4 | 11:00 | 67 / 80 / 80 | 33 / 40 / 70 | - | - |
| 2026-11-10 | P1 | 09:00 | 67 / 60 / 70 | 33 / 80 / 60 | 33 / 80 / 60 | 67 / 80 / 60 |
| 2026-11-10 | P2 | 10:00 | 67 / 80 / 90 | 33 / 80 / 60 | 33 / 80 / 60 | 67 / 80 / 70 |
| 2026-11-10 | P3 | 11:00 | 67 / 60 / 80 | 33 / 80 / 60 | 33 / 80 / 60 | 67 / 80 / 70 |
| 2026-11-10 | P4 | 11:00 | 67 / 60 / 80 | 33 / 80 / 60 | 33 / 80 / 60 | 67 / 80 / 70 |

Pooled over days (mean, 95% day bootstrap when n >= 5):

| cut | days | API rank | LM | API - LM top 3 | blend (days) |
|---|---|---|---|---|---|
| P1 | 6 | 72.2 [56, 89] / 56.7 [47, 67] / 68.3 [63, 73] | 38.9 / 60.0 / 76.7 | +33.3 [+6, +56] | 66.7 / 72.0 / 74.0 (5) |
| P2 | 6 | 66.7 [50, 83] / 70.0 [57, 80] / 80.0 [73, 87] | 38.9 / 60.0 / 76.7 | +27.8 [+0, +50] | 60.0 / 80.0 / 84.0 (5) |
| P3 | 6 | 72.2 [56, 89] / 76.7 [70, 80] / 81.7 [72, 88] | 38.9 / 60.0 / 76.7 | +33.3 [+6, +56] | 73.3 / 76.0 / 84.0 (5) |
| P4 | 6 | 72.2 [56, 89] / 76.7 [70, 80] / 81.7 [72, 88] | 38.9 / 60.0 / 76.7 | +33.3 [+6, +56] | 73.3 / 76.0 / 84.0 (5) |

### B. The 00:05 pull's API dailyRank vs final, per day

| day | share ranked | votes visible | API rank at 00:05 | LM |
|---|---|---|---|---|
| 2026-10-28 | 1.0 | 31 | 100 / 100 / 80 | 0 / 40 / 80 |
| 2026-10-29 | 0.9 | 0 | 33 / 60 / 50 | 67 / 60 / 60 |
| 2026-10-30 | 1.0 | 0 | 100 / 80 / 70 | 67 / 100 / 90 |
| 2026-10-31 | 0.91 | 0 | 67 / 40 / 70 | 67 / 80 / 70 |
| 2026-11-01 | 1.0 | 19 | 100 / 100 / 90 | 67 / 80 / 80 |
| 2026-11-02 | 0.94 | 0 | 33 / 60 / 70 | 33 / 80 / 90 |
| 2026-11-03 | 0.95 | 0 | 33 / 40 / 50 | 33 / 60 / 80 |
| 2026-11-04 | 1.0 | 0 | 33 / 40 / 40 | 33 / 40 / 80 |
| 2026-11-08 | 1.0 | 0 | 67 / 60 / 70 | 67 / 60 / 80 |
| 2026-11-09 | 0.92 | 0 | 0 / 40 / 60 | 33 / 40 / 70 |
| 2026-11-10 | 1.0 | 0 | 0 / 20 / 50 | 33 / 80 / 60 |
| mean (11 days) | | | 51.5 / 58.2 / 63.6 | |

Notes on B: Oct 28 and Nov 1's 00:05 pulls ran late, with votes already visible (31 and 19 launches), so they are not
pre-reveal reads. Without them, the API rank at 00:05 averages 40.7 / 48.9 / 58.9 over 9 days, **below the LM**. At
00:05 the hidden order has almost no votes behind it.

### C. How early does the hidden rank beat the LM? (15-min posts_ts, Nov 4, 8, 9, 10; results/api_rank_earliest.json)

| day | first read (UTC) | LM top 3 | earliest minute the API rank beats the LM on top 3 and stays there | API top 3 at 20 / 30 / 45 / 60 / 75 / 90 min |
|---|---|---|---|---|
| Nov 4 | 08:15 | 33 | 50 | 67 / 67 / 33 / 67 / 67 / 67 |
| Nov 8 | 08:01 | 67 | never (LM 67; API stays at 33) | 33 throughout |
| Nov 9 | 08:01 | 33 | 35 | 33 / 33 / 67 / 67 / 100 / 100 |
| Nov 10 | 08:01 | 33 | 65 | 0 / 0 / 0 / 0 / 67 / 67 |

**What the rank is at 00:01–00:15.** Spearman of the first read's rank:

| day | vs LM | vs launch id (scheduled order) | vs final |
|---|---|---|---|
| Nov 4 | 0.35 | 0.14 | 0.41 |
| Nov 8 | 0.48 | −0.49 | 0.46 |
| Nov 9 | 0.33 | 0.05 | 0.59 |
| Nov 10 | 0.26 | −0.27 | 0.34 |

So it is not the scheduled order and not the LM. It is already a vote order, but built on the first few minutes of votes, so it is noisy.

**Verdict.** The pre-reveal call becomes useful about 35–65 minutes after launch (00:35–01:05 PT) on 3 of 4 days. Before that the LM is as good or better. The hourly pipeline reads (6 days) give +33 top 3 over the LM from the 01:00 read [+6, +56]. The 00:05 read (9 clean days) is worse than the LM.
