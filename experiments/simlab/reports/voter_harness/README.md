# Voter-based 00:05 forecast harness (orchestrator 22:53Z Nov 12)

Script: voter_harness.py. Re-run on a new store snapshot:

    EDGES=none|hunter|hunter_maker [CURVE=0] python voter_harness.py <store dir> <clean_live_rows_nosite.parquet> <launches dir> <salt dir> <out dir>

Setup:
- Days: Oct 29–31, Nov 2–4, 8–11. Clean baseline = PH agent's clean_v3_nosite (as live): top 3/5/10 = 63.3 / 72.0 / 74.0, #1 in top 3 on 10 of 10 days.
- Covered people: 39,774 complete people in the store snapshot of Nov 10.

**Coverage of the test days' votes by covered people:**
- Oct 29 – Nov 4: 0.29–0.42.
- Nov 8: 0.26. Nov 9: 0.13. Nov 10: 0.00. Nov 11: no data.
- The store's reads end Nov 10, so the later days are barely covered.

| variant | gain vs clean, top 3 / 5 / 10 / #1-in-top-3 [95% day bootstrap] |
|---|---|
| no edges, STRICT (reads fetched before the day) | 0.0 / 0.0 / 0.0 / 0.0 (weight 0 chosen leave-one-day-out) |
| no edges, LENIENT (any read of an earlier-day upvote) | 0.0 / 0.0 / 0.0 / 0.0 |
| + follows the hunter, STRICT | −6.7 [−16.7, 0.0] / −2.0 / −2.0 / −10.0 |
| + follows the hunter, LENIENT | 0.0 / 0.0 / 0.0 / 0.0 |
| + follows the hunter or first named maker, STRICT / LENIENT | −6.7 / 0.0 (same as hunter only) |
| launch-level active-followers score instead of E (hunter), STRICT / LENIENT | −3.3 [−10.0, 0.0] / 0.0 |
| hidden window (re-reads 00:05–04:00 PT that already show today's votes) | 0.0. Only 14 people were re-read in the window across all days (Nov 3: 4, Nov 4: 9, Nov 10: 1). |

**Reading:**
- On held data, voter-expected votes and follower counts add nothing to the clean 00:05 score. The leave-one-day-out weight is 0 on held-out days.
- With strict timing, follower edges hurt: the weight chosen on other days overfits.
- The clean score leaves little headroom on these days: #1 already in the top 3 on every day.

**Coverage curve:**
- The run with the curve was killed by a container restart.
- Because the gain is exactly 0 at full current coverage, a curve over lower coverage cannot show a rising slope on held data.
- There is no evidence today that more coverage would help.
- The hidden-window variant is the one that needs new data: fresh re-reads between 00:05 and 04:00 PT. Today there are 14.
