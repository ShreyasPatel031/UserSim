# Votes on comments before the reveal (Nov 11), and the comment ridge's train/serve check

**Source.** raw/ph_at_launch/<day>/api_comments/<YYYYMMDD>T<HHMM>PT.jsonl, the official API's per-snapshot read of every
comment with its votesCount at that read. live/comments_ts.jsonl keeps each comment only once (its first sighting),
so it cannot give vote growth.

**Days with reads before the reveal:** Nov 4 (from 00:01 PT), Nov 8 (from 01:31), Nov 10 (from 01:30), Nov 11 (from
01:30; scored once its final ranks exist). Nov 9 has none. So P1 exists only on Nov 4. **Three days, no intervals.**

Per-day replay (comment_votes.py replay → results/comment_votes_replay.json): the five vote features alone
(cv_sum / cv_max / cv_maker1 / cv_per_out / cv_growth1h, LM breaks ties) next to the comment ridge, the API rank, the
blend and the LM. At P4, top 3 / 5 / 10:

| day | cv_sum | cv_maker1 | cv_growth1h | ridge | API rank | blend | LM |
|---|---|---|---|---|---|---|---|
| Nov 4 | 33 / 40 / 80 | 33 / 40 / 70 | 0 / 40 / 90 | 33 / 60 / 90 | 67 / 60 / 90 | 100 / 60 / 90 | 33 / 40 / 80 |
| Nov 8 | 33 / 60 / 80 | 67 / 60 / 80 | 0 / 40 / 80 | 67 / 60 / 80 | 33 / 80 / 80 | 33 / 80 / 90 | 67 / 60 / 80 |
| Nov 10 | 33 / 80 / 70 | 67 / 80 / 70 | 67 / 80 / 50 | 33 / 80 / 60 | 67 / 80 / 80 | 67 / 80 / 70 | 33 / 80 / 60 |

- No vote feature beats the API rank or the blend. cv_maker1 (votes on the team's first comment) is the steadiest of them.
- From Nov 12 they are recorded as extra columns in every P-point file (cv_sum, cv_max, cv_maker1, cv_per_out,
  cv_growth1h, cv_snapshot), with pred_rank unchanged, so they accrue for a refit at 7+ days.
- Note: cv_snapshot is the read's planned PT time, at or before T. The fetch itself can finish seconds to minutes after it.

**Train/serve mismatch of the comment ridge.** Training used the top-50-threads page dump; live sees every comment.
- Comments created by the P point that fall in threads outside the day's top 50 (by end-of-day votes): **0 of 54–114 on Nov 4, 0 of 26–37 on Nov 8, 0 of 58–83 on Nov 10**. In the first four hours the dump misses nothing.
- Volume, live vs training month, mean comments per launch: +1 h 2.08 vs Oct 1.72 (×1.21), +2 h 2.51 vs 2.42 (×1.04), +4 h 3.38 vs 3.43 (×0.99). **No rescale.**
- Unique non-team commenters run higher live: +1 h ×2.0, +2 h ×1.6, +4 h ×1.6 vs October. Not a stable factor, so not rescaled.
  - Likely cause: live identifies the team by people_ts user ids (makers + hunter). Training identifies it only by named makers, and placeholder makers can't be matched, so their comments count as "outside" in training.
  - Expected effect: the ridge sees live launches with a few more outside commenters than training would. The order within a day matters more than the level, so this probably moves little. Watch it in the forward scores.
