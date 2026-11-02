# Pre-launch X engagement over the honest day-calibrated control: go/no-go (Nov 2, 2026, 18:40 UTC)

Code: `simlab/x_prelaunch_e1.py`; data `reports/x_prelaunch_e1.json`. Runs without a VM.

**Rule fixed before any run:** X adds daily value iff, on at least 10 full days, daily top 3 against the honest
day-calibrated control has a 95% interval above 0.

**Data.** Gate `raw/x/prelaunch_wip/dm_gate.json` (day-matched: every team handle's [day−30, day) window fetched,
posts complete, engager lists done): 235 covered launches (144 with posts), 16 full October days (Oct 2, 3, 5, 8, 11,
12, 14, 16, 17, 18, 20, 21, 22, 23, 24, 25). The paid twitterapi credit is spent, so this is the dataset for now; the
gate also lists 2,552 Jul–Oct launches but no full day before October.

**Honest X inputs** (dated before 00:00 PT on launch day): team posts in the 30 days before, and distinct engagers whose
reply / quote is dated before the cutoff. Reposts (no time) and the like / impression / reply counts (read after launch)
are not used.

**Model.** log mu = log mu_honest + a_day + b · [log(1 + posts), log(1 + engagers)], Poisson with day fixed effects,
fitted forward only on covered launches of strictly earlier days (≥ 5 days, ≥ 30 launches). The control's daily ranking
is the honest launch model's (day calibration is constant within a day). 13 of the 16 full days have enough earlier
history to be scored (Oct 2, 3 and 5 do not).

| X − control, 13 full days | Daily top 3 | Top 5 | Top 10 |
|---|---|---|---|
| Difference | +0.0 [0.0, 0.0] | −3.1 [−7.7, +0.0] | +0.0 [0.0, 0.0] |
| Days better / tied / worse | 0 / 13 / 0 | 0 / 11 / 2 | 0 / 13 / 0 |
| October totals (X vs control) | 59.0 vs 59.0 | 56.9 vs 60.0 | 76.9 vs 76.9 |

Weekly: no fully covered week (Monday–Sunday), so no weekly result. Early read over all covered launches (15 days,
235 launches): top 3 among covered +0.0, top 5 −1.3 [−4.0, +0.0]. Within-day Spearman of the X inputs with the honest
model's residual: engagers −0.03, posts +0.02. The forward-fitted coefficients shrink to about 0 as days accumulate
(Oct 25: posts −0.0004, engagers +0.010).

**Verdict: no-go.** Pre-launch X engagement does not add daily value over the honest day-calibrated control: daily top 3
is unchanged on every scored day, top 5 is slightly worse, and the inputs carry no within-day signal about the honest
model's error. Together with the person-level result (`x_tie_pool.md`: X-tied pool people vote at 13.7× but are too few
to move the pool), X as fetched here (team posts and their dated engagers, 30 days before launch) is not the source of
the launch-day shock. The hourly re-run is stopped.
