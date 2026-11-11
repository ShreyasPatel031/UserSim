# Error anatomy of the launch model's daily top-3 misses

5,564 launches, 239 days (honest out-of-fold, Mar 1 - Oct 25). Among each day's actual top 3: hit 441, near (predicted 4-10) 241, miss (predicted > 10) 33; false alarms (predicted top 3, finished > 10) 46.

## Group means

| attribute | hit | near | miss | false alarm | other |
|---|---|---|---|---|---|
| team_prev | 657.64 | 803.71 | 469.76 | 722.87 | 403.49 |
| team_prev_top3 | 149.41 | 169.42 | 91.30 | 154.13 | 79.42 |
| hunter_prev | 117.05 | 84.63 | 18.58 | 80.33 | 28.81 |
| relaunch | 0.08 | 0.05 | 0.06 | 0.09 | 0.04 |
| n_makers | 4.00 | 2.35 | 1.94 | 2.56 | 1.71 |
| self_hunted | 0.05 | 0.17 | 0.42 | 0.09 | 0.53 |
| desc_len | 349.44 | 321.83 | 295.64 | 312.02 | 330.33 |
| tagline_len | 47.94 | 47.45 | 46.61 | 48.13 | 47.59 |
| weekday | 2.98 | 3.10 | 2.85 | 2.67 | 2.53 |
| lineup | 22.62 | 23.52 | 30.33 | 32.59 | 34.26 |
| ai_topic | 0.76 | 0.66 | 0.55 | 0.67 | 0.49 |
| topic:Artificial Intelligence | 0.76 | 0.66 | 0.55 | 0.67 | 0.49 |
| topic:Productivity | 0.32 | 0.24 | 0.39 | 0.17 | 0.31 |
| topic:Developer Tools | 0.30 | 0.39 | 0.24 | 0.20 | 0.30 |
| topic:GitHub | 0.08 | 0.16 | 0.24 | 0.02 | 0.17 |
| topic:Open Source | 0.09 | 0.15 | 0.12 | 0.04 | 0.12 |
| topic:Mac | 0.01 | 0.04 | 0.06 | 0.00 | 0.08 |
| topic:SaaS | 0.07 | 0.07 | 0.03 | 0.07 | 0.07 |
| topic:Marketing | 0.14 | 0.07 | 0.06 | 0.13 | 0.06 |
| topic:Design Tools | 0.06 | 0.04 | 0.03 | 0.13 | 0.06 |
| topic:API | 0.08 | 0.07 | 0.03 | 0.04 | 0.04 |
| topic:Menu Bar Apps | 0.00 | 0.01 | 0.12 | 0.00 | 0.05 |
| topic:Tech | 0.03 | 0.03 | 0.03 | 0.09 | 0.04 |
| c_4h | 17.01 | 11.08 | 9.21 | 3.61 | 3.46 |
| c_day | 46.56 | 31.63 | 31.36 | 6.83 | 9.18 |

## What the model under-predicts: Spearman of the within-day residual (log votes - prediction) with each attribute (within-day centered), 95% day-bootstrap

| attribute | rho [CI] |
|---|---|
| c_day | +0.433 [+0.405, +0.457] |
| c_4h | +0.300 [+0.273, +0.326] |
| topic:Developer Tools | +0.054 [+0.030, +0.079] |
| topic:GitHub | +0.046 [+0.025, +0.067] |
| team_prev | -0.041 [-0.067, -0.017] |
| self_hunted | +0.040 [+0.013, +0.070] |
| team_prev_top3 | -0.039 [-0.065, -0.012] |
| topic:Open Source | +0.034 [+0.010, +0.056] |
| ai_topic | -0.031 [-0.062, -0.003] |
| topic:Artificial Intelligence | -0.031 [-0.058, -0.002] |
| desc_len | +0.022 [-0.003, +0.048] |
| n_makers | -0.019 [-0.049, +0.012] |
| hunter_prev | -0.015 [-0.046, +0.020] |
| relaunch | -0.015 [-0.037, +0.005] |
| topic:Productivity | +0.015 [-0.013, +0.043] |
| topic:Menu Bar Apps | +0.015 [+0.003, +0.030] |
| topic:API | +0.010 [-0.010, +0.028] |
| topic:SaaS | -0.009 [-0.026, +0.010] |
| topic:Marketing | -0.008 [-0.027, +0.011] |
| tagline_len | +0.004 [-0.022, +0.031] |
| weekday | +nan [+nan, +nan] |
| lineup | +nan [+nan, +nan] |
| topic:Mac | +0.009 [-0.006, +0.026] |
| topic:Tech | +0.002 [-0.015, +0.018] |
| topic:Design Tools | +0.001 [-0.013, +0.019] |

## Reading (hypotheses, not tests)

1. **Hard misses** (finished top 3, predicted >10; 33 launches) are indie, community-driven launches:
   - self-hunted 42% (hits 5%), 1.9 makers (hits 4.0), hunters with few past hunts (19 vs 117);
   - over-represented in GitHub / Open Source / Mac / Menu Bar / Productivity topics, less AI;
   - bigger line-ups (30 vs 23);
   - yet they draw early comments (9.2 by 04:00 PT vs 3.5 for the rest).

   The model leans on hunter and team reach, so it cannot see organic pull before launch.
2. **Near misses** (predicted 4–10; 241 launches) are most top-3 errors. They differ from hits mainly in early comments (11 vs 17 by 04:00 PT), so this is an ordering problem that early engagement fixes. That matches the P-point comment ridge result.
3. **False alarms** (predicted top 3, finished >10; 46 launches) have big teams and hunters (team_prev 723) but almost no early comments (3.6 by 04:00 PT, like ordinary launches). The model over-trusts reach; early comments would demote them.
4. **Residuals:** within-day log-vote residuals rise with Developer Tools / GitHub / Open Source and self-hunting, and fall with team history and the AI topic. Every effect is small (|rho| ≤ 0.05) except comments (+0.30 at 4 h, +0.43 by day end; those are post-00:05).

**Next hypotheses for 00:05 features:**
- (a) **Pre-launch GitHub momentum** (repo stars / star velocity before launch day, dated) for GitHub / Open Source launches. raw/github_repos and raw/github_stargazers exist and may carry dates.
- (b) **Indie maker audience** for self-hunted launches: the maker's own X/PH audience dated before launch. Only the follower counts read at 00:05 are honest.
- (c) **Upcoming-page activity before 00:00** (comments created before the launch day): honest at 00:05, and the comment dump already holds it.

**Test of (c), Nov 11:** comments created before 00:00 PT (the upcoming page) as 00:05 features, using the same ridge
as comment_forecast.py, month-forward over 207 days.
- 89% of launches have one, but the mean is 1.0: mostly the maker's first comment.
- Ridge minus LM: top 3 −0.3 [−2.3, +1.4], top 5 +0.6 [−0.5, +1.6], top 10 −0.2. **No gain.**
- The comment signal only appears after 00:00 PT, as the P1–P4 points.
