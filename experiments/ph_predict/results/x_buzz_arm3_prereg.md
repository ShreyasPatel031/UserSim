# X pre-launch buzz vs arm 3 — PRE-REGISTERED (orchestrator 21:38Z Nov 18). Committed before any number is computed.

Question: does Grok Bot's pre-launch X post count, frozen before 00:00 PT D, improve the published 00:05 arm 3 order?

## Inputs (leak rules)
- **X feature, pre_launch window only:** the window must end at or before D 00:00 PT (08:00Z); this is asserted per row.
  - Nov 10–14: `x_buzz_backfill.jsonl`, `pre_post_count` with `pre_window_end` = D 08:00Z. These were fetched later with the count API, but they count only posts dated before the cut.
  - Nov 15 onwards: `x_buzz_0010.jsonl`, window `pre_launch`, with `window_end` = D 08:00Z.
  - Nov 13's 0010 file is NOT used: its window ends 08:17Z, after the cut. The Nov 13 backfill is used instead.
  - Nov 8–9 backfill rows are `window_partial`, so those days are secondary only and excluded from the primary result.
  - launch_day counts are never used.
- **Features:** x1 = log1p(pre-launch posts); x2 = maker_preannounced_ph_launch (0/1).
- **Name collisions:** rows Grok flags as a name collision or exclusion are treated as missing, not as zero.
  - Missing x1 is set to the day's median before z-scoring.
  - The flags are counted and reported.
- **No PH vote or rank field** is in the X inputs; this is asserted on column names.
- **Arm 3 score:**
  - Nov 16–17 use the live arm-3 score (shadow_arm3 / published parquet).
  - Other days use arm3_live.predict(D) replayed on the VM from the frozen 00:05 line-up (data/today/D.json). Training is on days < D only, as live; the replay was DRY, with uploads refused.
  - Source per day is recorded.
- **Truth:** truth_daily.json final daily ranks; an unranked launch is a miss.

## Lines
1. arm 3 alone: z(arm3) within day.
2. Re-ranker: z(arm3) + w1 · z(x1) + w2 · x2.
   - Grid: w1 in {0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0}; w2 in {0, 0.25, 0.5}.
   - Chosen leave-one-day-out: for each held-out day, the grid point with the most top-5 + top-3 hits on the other days.
   - Ties go to the smaller w1, then the smaller w2.
3. Grok's frozen X-only top 10 (results/grok_forecast/D_0030.json), scored as is.
   - It is not leak-free for 00:05: it also uses launch_day counts to about 00:22 PT.
   - It is reported for reference only.

## Metric and decision
- **Metric:** top 3/5/10 hits per day. PRIMARY = line 2 minus line 1, paired by day, day bootstrap 95% interval (10,000), n days stated.
- **Placebo:** shuffle x1 and x2 across launches within each day (200 shuffles) and rerun the LODO. The mean difference should be about 0.
- **Decision:**
  - If the primary interval's lower bound is > 0 on top 3 or top 5, it is written up as a deploy candidate under the model rule.
  - Otherwise it becomes a scored forward shadow line, with the n days needed for an interval clear of 0 (from the observed mean and sd).
- **Primary days:** Nov 10 to the last day with truth at run time, excluding days without arm 3 or X.

## Amendment 1 (22:05Z Nov 18, before any result was computed)
The arm-3 replay for past days is not leak-free, and no result has been computed from it.
- On the VM, a past day D exists only as a finished day file, `days/D.json`, which carries values read after the fact. `arm3_live` reads the line-up from that file, not from the frozen 00:05 file.
- The shared feature files (cm/aud/... features) were built after D.
- The DRY replay therefore refused every past day: "no 00:05 line-up rows". Patching around that would mix in later data.

Revised baseline: **the published 00:05 score as written that night** (`raw/daily/D/forecast_D.parquet`).
- `pred_arm3` where present (Nov 17 on).
- Otherwise `pred_arm2` (Nov 14–16).
- Otherwise `pred`, the published model of the night (Nov 10–13).
- Source per day is recorded.

Analyses:
- PRIMARY = all primary days on this as-of-night baseline.
- SECONDARY = the arm-3 days only (live arm 3: `shadow_arm3` Nov 16, published from Nov 17), reported with its n.

Everything else is unchanged.
