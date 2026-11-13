# Before-launch held-follower count (orchestrator 04:55Z Nov 13)

Scripts: follow_shadow.py (nightly; a script only, nothing scheduled) and follow_pre_eval.py.

**Definition.** Team = the hunter plus the makers in that day's 00:05 read. A team's count only uses complete people whose following tab was pulled before 00:00 PT on the launch day, so every counted edge provably predates the launch.

**Store limit.** The store I hold is the Nov 10 snapshot (39,774 complete people). Nov 10 therefore has 37,446 eligible people; Nov 11 and 12 have all 38,507, so pre = all on those days.

| | Nov 10 (50 launches) | Nov 11 (16) |
|---|---|---|
| eligible held people | 37,446 | 38,507 (all) |
| launches with ≥ 1 pre-launch held follower | 56% | 81% |
| Spearman with final rank: pre / all edges / hunter PH followersCount / clean | 0.42 / 0.42 / 0.43 / 0.47 | 0.67 / 0.67 / 0.66 / 0.80 |
| partial beyond clean_v3_nosite: pre / all / hunter followersCount | +0.12 / +0.12 / +0.15 | +0.28 / +0.28 / +0.29 |
| Spearman(pre count, hunter PH followersCount) | 0.93 | 0.96 |
| leak: (all − pre), top 10 / others; median all/pre ratio | +152 / +5.9 mean; 1.045 / 1.0 | 0 (no later pulls) |

th_n_pre is not held, so the base is clean_v3_nosite alone.

**Reading.**
1. The held count is almost the same thing as the hunter's PH followersCount (rank correlation 0.93–0.96). That count is in the 00:05 read and is clean. Taken alone it gives the same partial correlation. So the follower signal is real at 00:05, but it comes from the public followersCount; held edges add nothing on top.
2. The direct leak (edges from the 1,061 people pulled on the launch day) is small at the median: 1.045 for the top 10 against 1.0 for the rest. The mean is +152 for top-10 teams, driven by large hunters.
3. ph_hunter_followers is already in the clean model, yet the 00:05 followersCount still shows a partial of +0.15 / +0.29. It is worth checking which read the clean model's value comes from. It may be stale or captured differently.

**Days needed.** About 9 days to detect a partial of 0.2 (two-sided 5%, 80% power). This assumes a per-day sd of 0.21, taken from the 14-day follower partials.

**Shadow output.** Nov 12 output, ids and counts only: gs://…/usersim_sim/tmp/e5/follow_shadow/shadow_2026-11-12.jsonl.
