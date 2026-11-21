# Pre-registration: team held share at 00:05 vs the 00:05 line's accuracy (orchestrator 21:28Z Nov 21; deadline Nov 23 12:00Z)

Written before any number is computed.

## Question
Does the share of a launch's team (makers and hunter) held complete in the population store at 00:05 PT predict whether the published 00:05 line ranks that launch correctly?

## Data
- **Days:** every day with team_pulled_0100 rows (from Nov 12), a published 00:05 forecast (raw/daily/<d>/forecast_<d>.parquet; pred_arm3 if published_model is arm3, else pred_arm2) and final ranks (results/web/truth_daily.json, >= 10 ranked).
  - Expected days: Nov 14–20 (7), plus Nov 21 and 22 if final ranks exist by the deadline.
  - That is fewer than the 14 asked; the report says so.
- **Held share (leak check):**
  - For day d, use the newest store_v3 copy whose publish time (events.parquet generation) is at or before d 00:05 PT. These are local copies, keyed by generation, in the PH ops scratchpad.
  - Run E5's team_shadow.py (claude/person-model-v2 fcbcd617, as deployed) on d's 00:05 line-up with that copy.
  - held share = n_team_complete / n_team per launch. Launches with n_team = 0 are dropped.
  - Never use a copy published after 00:05 PT. The nightly team_shadow files from Nov 18 on read a copy published around 01:00 PT, so they are NOT used.
- **Truth:** truth_daily ranks. Unranked launches (dropped from featured) are excluded from the per-launch tests.

## Outcomes and tests (day-clustered bootstrap, 10,000 draws, seed 0)
1. **Primary, top 3:**
   - Among each day's true top 3, hit = 1 if the 00:05 line had that launch in its top 3.
   - Compare the hit rate of launches with held share >= the pooled median of true-top-3 launches ("high") against those below it ("low").
   - Report the difference with a 95% CI.
2. **Per-launch rank error:** |log(pred_rank) − log(final_rank)| over all ranked launches, as a Spearman correlation with held share, with a CI.
3. **Per day:** the day's top-3 hits (0–3) against the day's mean held share, as a Spearman correlation. Descriptive only; there are few days.
4. **Upper bound if all teams were held:** (hit_high − hit_low) × (share of true-top-3 launches in the low group) × 100, in top-3 points.
   - This assumes the association is causal, so it is an upper bound.
   - CI from the same bootstrap.

## Decision
- Report once.
- "Matters" only if the primary CI excludes 0.
- With 7–9 days the test is expected to be underpowered. If the CI covers 0, the report gives the days needed at the observed effect.

## Amendment 1 (Nov 21 ~21:55Z, before any outcome number was seen)
- **Problem:** the median held share among true-top-3 launches is 0. On 7 scored days, 14 of 21 true-top-3 launches have no team member held at 00:05. A ">= median" split therefore puts every launch in "high" and leaves "low" empty.
- **New split:** high = held share > 0 (at least one team member held complete at 00:05); low = held share = 0.
- **Unchanged:** all other tests and the upper-bound formula.
