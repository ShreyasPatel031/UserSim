# Late builders: votes after the 04:00 PT reveal (hourly reads, 6 days: 2026-11-02, 2026-11-03, 2026-11-04, 2026-11-08, 2026-11-09, 2026-11-10)

Launches: 182. Median share of final votes arriving after 04:00 PT: 0.191.

Spearman with late_share: gap -0.02, lm_pos -0.72, api_pos -0.73, weekend +0.17, lineup -0.34, n_makers +0.41, self_hunted -0.53
Spearman with rise (hidden rank at 03:00 - final rank): gap +0.38, lm_pos -0.16, weekend -0.01, lineup -0.04, n_makers +0.03, self_hunted -0.08

LM top-5 launches, mean rise by gap (hidden rank - LM rank at 03:00): {"mean": {"hidden >= LM": -0.17, "gap 1-3": 0.43, "gap > 3": 2.91}, "size": {"hidden >= LM": 12, "gap 1-3": 7, "gap > 3": 11}}

Correction of the 03:00 best recipe (0.75 API + 0.25 LM), mean over days, top 3 / 5 / 10:

| candidate | top 3 / 5 / 10 |
|---|---|
| beta_0.0 | 83.3 / 80.0 / 80.0 |
| beta_0.1 | 83.3 / 76.7 / 80.0 |
| beta_0.25 | 72.2 / 76.7 / 85.0 |
| beta_0.5 | 61.1 / 73.3 / 85.0 |
| weekend_w0.5 | 83.3 / 80.0 / 81.7 |

Leave-one-day-out: 83.3 / 80.0 / 80.0 (picks: weekend_w0.5, weekend_w0.5, weekend_w0.5, beta_0.0, weekend_w0.5, weekend_w0.5).

## Reading

**Late builders exist.**
- Median share of final votes arriving after 04:00 PT is 19%. It is larger for bigger launches (Spearman with LM position −0.72) and for team launches (n_makers +0.41, self-hunted −0.53).
- The gap "LM ranks it higher than the 03:00 hidden rank" predicts a later rise (Spearman +0.38 with rise). Among the LM's top 5, launches with gap > 3 rose 2.9 places on average (11 launches), vs −0.2 when hidden ≥ LM.

**As a correction it does not pay on top 3.**
- Rewarding the gap (β 0.25 / 0.5) buys top 10 (+5) but costs top 3 (−11 / −22).
- The weekend switch (w_api 0.5 on Sat/Sun) keeps 83.3 / 80.0 and adds +1.7 top 10. LODO picks it on 5 of 6 days but lands on 83.3 / 80.0 / 80.0, the same as the plain recipe.
- From Nov 12, pred_rank_best2 (the weekend switch) is written next to pred_rank_best, so the two can be compared forward.
- E5's Wayback curves (another branch) were not needed for this answer, and there is no hidden rank on those days.

## P0 (00:45 PT, 15-min data, 4 days; results/p0_replay.json)

| scorer | top 3 / 5 / 10 |
|---|---|
| LM | 41.7 / 55.0 / 72.5 |
| API rank | 33.3 / 55.0 / 67.5 |
| 0.5 API + 0.5 LM | **50.0 / 65.0 / 77.5** |

Live from Nov 12: point P0 in the comment writer (comment ridge with P1's coefficients; API rank; pred_rank_best = the 0.5 mix). It is written by the 02:17 PT run along with P1/P2 (honest: data ≤ 00:45).

## Mid-day weekly call with est_votes (before the reveal, 03:45 PT; results/weekly_estvotes_replay.json)

Today's launches placed into the running weekly list by est_votes, scored against the week-so-far list at the day's end.
Nov 8 is unusable: the week's Nov 5–7 launches have no day-end votes held (no posts_ts or vote_snapshots for those days), so its list is incomplete. 3 valid days (Nov 4, 10, 11), top 3 / 5 / 10:

| scorer | top 3 / 5 / 10 |
|---|---|
| earlier days only | 77.8 / 73.3 / 63.3 |
| + today by est_votes | 77.8 / 73.3 / 66.7 |
| + today by est_votes × 2 | 77.8 / 80.0 / 86.7 |
| + today at R0+4h × 1.069 (weekly_live r4, 4 h later) | 77.8 / 86.7 / 86.7 |

est_votes at 03:45 sits at roughly half of the day-end level. Scaled ×2 (to be fitted on more days), it gives the weekly call about 4 hours earlier than the R4 point, with top 10 at the same level.
