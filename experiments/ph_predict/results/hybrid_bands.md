# 03:45 hybrid: more replay days and the accuracy-vs-read-time curve (orchestrator 15:36Z Nov 14; held data, no fetches)

Inventory of pre-reveal order reads (00:05-03:59 PT, hidden rank / API order):
- raw/vote_snapshots (pipeline hourly recorder, rank_now): 00:06, 01:00, 02:00, 03:00 PT on Nov 2-13 (Oct 31 and Nov 1 files start after 04:00 PT).
- ph_at_launch/<d>/live/posts_ts (15-min capture, daily_rank_at_fetch): pre-reveal reads on Nov 2-13 only (Oct 27-Nov 1 captures are later in
  the day); Nov 14 none (capture down).
- Wayback homepage captures (Jul-Oct): the homepage order is randomised while votes are hidden (archive README), so not a hidden-rank read.
- exp-1 intraday loop: Nov 3 on (same days); pipeline rereads: the ranks step re-reads finished days only.
So the replayable set is Nov 2-13 = 12 days (Nov 13 new; Nov 14 scores tomorrow). 11 of the 12 are inside the frozen weights' fit window (Nov 2-12).
Clean prior: 00:05 parquet pred; Nov 2 and 5-7 use the month-fold clean_nosite stand-in (as hybrid_vmonly.py).

| read band (recorder) | n | hybrid (published line) | hidden rank alone | ridge alone | slots6 by 00:05 prior | 00:05 model alone |
|---|---|---|---|---|---|---|
| 01:00 PT | 12 | 69.4 / 58.3 / 70.0 | 69.4 / 58.3 / 64.2 | 69.4 / 65.0 / 70.0 | 69.4 / 58.3 / 75.0 | 52.8 / 55.0 / 71.7 |
| 02:00 PT | 12 | 69.4 / 68.3 / 73.3 | 69.4 / 68.3 / 68.3 | 69.4 / 70.0 / 73.3 | 69.4 / 68.3 / 74.2 | 52.8 / 55.0 / 71.7 |
| 03:00 PT | 12 | 72.2 / 75.0 / 77.5 | 72.2 / 75.0 / 71.7 | 72.2 / 76.7 / 77.5 | 72.2 / 75.0 / 73.3 | 52.8 / 55.0 / 71.7 |
| 03:00 PT, Nov 13 only (outside the fit window) | 1 | 66.7 / 100 / 80 | 66.7 / 100 / 80 | 66.7 / 100 / 80 | 66.7 / 100 / 80 | 66.7 / 80 / 80 |

hybrid - hidden top 10 (paired day bootstrap): 01:00 +5.8 [+0.8, +10.0]; 02:00 +5.0 [+0.8, +9.2]; 03:00 +5.8 [+0.8, +10.8] (top 3/5 identical by
construction: the hybrid keeps the hidden top 5). Headline 03:00 read, 12 days: 72.2 / 75.0 / 77.5 vs the 11-day 72.7 / 74.5 / 77.3 - moves < 1 point.
Accuracy rises with read time mainly on top 5 (58 -> 68 -> 75). Nov 14's published file (hand-written from the 03:00 read) scores once its
final ranks land (tomorrow). The evidence stays thin: 12 days, 11 of them in the weights' fit window; more needs forward days.
