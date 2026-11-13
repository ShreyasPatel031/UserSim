# Team's own recent community engagement before launch (orchestrator 10:34Z Nov 13)

Scripts: team_engage.py and team_engage_safe.py (leak check). Data: the merged store (61,468 complete people) and 6,024 launches over 255 days (Mar 1 – Nov 10) with a clean 00:05 score (honest_preds_v2).

**Coverage.** 23.1% of launches have a complete hunter; 34.6% have a complete hunter or named maker. This is above the 15% gate.

Within-day results on covered launches, with day-bootstrap 95% CI:

| feature (team = hunter + named makers) | standardized difference, top 3 vs rest | partial beyond clean |
|---|---|---|
| upvotes given, prior 7 days | +1.01 [0.83, 1.19] | +0.205 [0.150, 0.259] |
| upvotes given, prior 30 days | +1.04 [0.86, 1.21] | +0.199 [0.143, 0.256] |
| distinct makers supported, 30 days | +1.05 [0.86, 1.23] | +0.205 [0.151, 0.260] |
| comments on other launches, 30 days | +0.29 [0.11, 0.50] | +0.053 [−0.006, 0.109] |
| forum posts, 14 days | +0.13 [−0.04, 0.33] | +0.041 [−0.033, 0.114] |
| days since last activity | +0.06 | −0.007 |

**Hunter only:** the same direction but weak. Upvotes in the prior 30 days give a partial of +0.078 [−0.004, 0.159].

**Beyond the hunter's followersCount** (only 3 days with forecast files, Oct 28 onward): team upvotes in 7 days +0.32 [0.02, 0.58]. Too few days to rely on.

**Month-forward ridge on top of clean** (193 days, team block plus coverage flag):
- hunter + makers: top 3 **+2.9 [+1.0, +5.0]**, top 5 0.0, top 10 −0.3;
- hunter only: about 0.

**Leak check, the key caveat.** Upvote rows are snapshots, dated by the acted-on launch's day. A maker who upvotes older launches after a successful launch would leak.
- Only 3.5% of the 30-day upvotes are provably cast before the target day (store ts_hi < day), and all of those are on November days.
- On those 4 days, using only provably-before upvotes, the partial is **+0.327 [0.165, 0.479]**.
- On launches with no post-launch-pulled rows, it is +0.29.

So the signal does not vanish when it is made provably clean, but that rests on 4 days.

**Other caveats.**
- Maker lists come from the warehouse launches table and may be later than 00:05.
- Being complete in the store is selected on voting activity in Oct – Nov (the seeded week), so the comparison is within-day among covered launches.

**Verdict.** The effect is promising, with a large standardized difference, but not yet proven clean. Every pull in the merged store finished by Nov 12, so from Nov 13 onward the feature is provably pre-launch for these people. Run it as a nightly forward shadow (team upvotes in 7 / 30 days, makers supported in 30 days, from people pulled before the day). About 9 days would detect a partial of 0.2.
