# Arm-3 live top-3 miss anatomy — PRE-REGISTERED (orchestrator 21:59Z Nov 18). Committed before any number is computed.

## Days
- Every live arm-3 day with truth_daily at run time.
- Nov 16 uses the shadow_arm3 file, the first forward day. From Nov 17 it is the published 00:05 arm 3 (`pred_arm3` in `raw/daily/D/forecast_D.parquet`).
- Expected n: Nov 16, 17, 18, 19 (whatever has truth by the run).

## Misses
A miss is a true top-3 launch (truth_daily final rank ≤ 3) that is not in arm 3's 00:05 top 3. For each miss I record:
- its arm-3 rank;
- its 00:05 inputs and those of arm 3's own top 3 that day, from the parquet and, where present, `arm3_inputs_D.parquet`:
  - hunter followers;
  - maker X followers;
  - company X followers;
  - promo reactions and promo posts;
  - known flag;
- its hidden-period signals at 03:45 from the P345 file (where present):
  - hidden rank `api_rank`;
  - comments `n_c`;
  - non-team unique commenters `u_out`;
  - `cv_sum`.

## Buckets, applied in order
- **(a) a feature present at 00:05 ranked it low:** on at least one of the five 00:05 inputs above, the miss is at or above the lowest value among arm 3's own top 3 that day, and that input is non-zero for the miss.
- **(b) no 00:05 signal, but visible by 03:45:** not (a), and at 03:45 the miss is in the day's top 3 by hidden rank `api_rank`, or in the top 3 by `n_c` or by `u_out`.
- **(c) no signal by 03:45:** neither.

## Outputs
- Bucket shares with counts.
- The single cheapest feature or rule that would have moved the most misses into the top 3. Cheapest means one input, or one rule, that is already computed.

## Test of that rule
- On the leak-free arm-3 backtest (`results/arm3_vs_arm2_preds.parquet`: 2026 Apr–Oct, 183 days; 2025 Mar–Dec, 204 days, month-forward), paired vs arm 3.
- Re-ranker z(arm3) + w · z(feature) within day. w is chosen from {0, 0.1, 0.2, 0.3, 0.5, 1.0} on the other months (leave-one-month-out), by top 5 + top 3; ties go to the smaller w.
- Top 3 / 5 / 10, day bootstrap 95% (10,000), n days.
- If the rule needs a 03:45 signal, it cannot be backtested on those 183 days, which have no recorder. In that case it is reported only on the forward days, as a shadow proposal.

## Decision
- If the top-3 or top-5 interval is clear of 0 in the 2026 test, it becomes a deploy candidate under the model rule.
- Otherwise it is a scored shadow line, with the n needed.
