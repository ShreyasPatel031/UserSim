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

## Follow-up (orchestrator 10:38Z): nightly script, leak size, stack test

**Nightly script.** team_shadow.py (not scheduled; handed to PH ops). Members count only if complete AND their upvotes tab was pulled before 00:00 PT of the launch day. It writes lag-1 and lag-2 variants. Coverage: Nov 12 12 / 37, Nov 13 4 / 20.

**Leak size** (team_leak_size.py; 3,597 team-member upvotes on older launches carrying cast-time bounds):

| target launch dated | cast after own launch (share of determinable) |
|---|---|
| 1 day before | 52 / 52 = 100% |
| 2–7 days before | 59% |
| 8–30 days before | 47% |

- Bounded rows come from page-1 reads, which show only recent votes, so the shares are biased upward.
- 10% of after-launch votes fall within 24 h of the launch.
- After-launch voting is not more common for top-10 teams (47% vs 68% for the rest), so the leak does not favour winners.
- A 2-day lag removes the 1-day window, where every determinable vote is post-launch. It does not remove all post-launch voting on older launches. Only pulling before the day (as team_shadow does) does that.

**Stack test** (team_stack.py; 176 days with thread data, 4,661 launches, 34.5% covered; month-forward ridge):

| | top 3 | top 5 | top 10 |
|---|---|---|---|
| clean + th_n_pre − clean | +3.6 [0.8, 6.4] | +1.4 [−0.3, 3.2] | +0.3 |
| clean + team − clean | +3.4 [1.3, 5.5] | +0.6 | −0.1 |
| **clean + th_n_pre + team − clean + th_n_pre** | **+0.8 [−1.1, 2.7]** | +0.2 [−0.9, 1.4] | +0.1 |
| same, LAG2 | +0.8 [−0.9, 2.3] | −0.1 | −0.2 |
| days with ≥ 40% covered (65): + team / + team LAG2 | +1.5 [−1.5, 4.6] / +2.1 [−0.5, 5.1] | +0.6 / +0.3 | +0.5 / +0.2 |

**Verdict.** The team block's gain over clean (+3.4) is largely the same signal as th_n_pre: pre-launch commenters are mostly the team's own network. On top of clean + th_n_pre it adds +0.8 overall, and about +1.5 to +2.1 on well-covered days, not distinguishable from 0.

Keep it as a forward shadow (team_shadow) for coverage and a clean read. Do not add it to the stack on this evidence.
