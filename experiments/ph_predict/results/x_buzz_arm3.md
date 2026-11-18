# X pre-launch buzz vs the published 00:05 line

Decision: NOT CLEAR: scored forward shadow line

## primary: n = 8 days
- base [np.float64(54.2), np.float64(62.5), np.float64(70.0)] / rerank [np.float64(54.2), np.float64(62.5), np.float64(71.2)] (top 3/5/10)
- rerank - base, day bootstrap 95%: top 3 [np.float64(0.0), np.float64(0.0), np.float64(0.0)], top 5 [np.float64(0.0), np.float64(0.0), np.float64(0.0)], top 10 [np.float64(1.3), np.float64(0.0), np.float64(3.8)]
- placebo (x shuffled within day, 200x) mean diff: [np.float64(-1.77), np.float64(-0.16), np.float64(-0.61)]
- LODO weights per day: {'2026-11-10': [0, 0.25], '2026-11-11': [0, 0.25], '2026-11-12': [0, 0], '2026-11-13': [0, 0.25], '2026-11-14': [0, 0.25], '2026-11-15': [0, 0.25], '2026-11-16': [0, 0.25], '2026-11-17': [0, 0.25]}; days changed: {'2026-11-17': [0.0, 0.0, 10.0]}
- n days needed for a clear result at this effect: top 3 None, top 5 None

## secondary_arm3_days: n = 2 days

## incl_partial_nov8_9: n = 10 days
- base [np.float64(53.3), np.float64(60.0), np.float64(71.0)] / rerank [np.float64(53.3), np.float64(60.0), np.float64(72.0)] (top 3/5/10)
- rerank - base, day bootstrap 95%: top 3 [np.float64(0.0), np.float64(0.0), np.float64(0.0)], top 5 [np.float64(0.0), np.float64(0.0), np.float64(0.0)], top 10 [np.float64(1.0), np.float64(0.0), np.float64(3.0)]
- placebo (x shuffled within day, 200x) mean diff: [np.float64(-1.37), np.float64(-0.24), np.float64(-0.46)]
- LODO weights per day: {'2026-11-08': [0, 0.25], '2026-11-09': [0, 0.25], '2026-11-10': [0, 0.25], '2026-11-11': [0, 0.25], '2026-11-12': [0, 0], '2026-11-13': [0, 0.25], '2026-11-14': [0, 0.25], '2026-11-15': [0, 0.25], '2026-11-16': [0, 0.25], '2026-11-17': [0, 0.25]}; days changed: {'2026-11-17': [0.0, 0.0, 10.0]}
- n days needed for a clear result at this effect: top 3 None, top 5 None

## Grok X-only frozen top 10 (reference, not leak-free for 00:05)
- per day: {'2026-11-13': [33.3, 20.0, 60.0], '2026-11-15': [66.7, 60.0, 70.0], '2026-11-16': [0.0, 20.0, 40.0], '2026-11-17': [33.3, 20.0, 50.0]}
- mean: [33.3, 30.0, 55.0]

## Diagnostics (computed after the pre-registered result; descriptive, not decisive)
- All-days grid, w2 = 0, 8 primary days, base → re-rank (top 3 / 5 / 10):
  - w1 = 0: 54.2 / 62.5 / 70.0
  - w1 = 0.1: 41.7 / 62.5 / 71.2
  - w1 = 0.2: 41.7 / 65.0 / 72.5
  - w1 = 0.3: 37.5 / 62.5 / 72.5
  - w1 = 0.5: 37.5 / 55.0 / 70.0
  - w1 = 1.0: 29.2 / 52.5 / 68.8

  Any weight on X posts lowers top 3, even in-sample.
- Per-day Spearman with the final rank: X posts 0.04–0.41 (median ~0.17) vs the published score 0.46–0.86. X carries less ranking information than the 00:05 score, and what it carries is largely already in that score.
- Leak checks:
  - every X window ends at or before D 00:00 PT (asserted per row);
  - the Nov 13 0010 file (window to 00:17 PT) is excluded and the backfill is used;
  - no PH rank or vote field is in the X inputs (asserted);
  - the placebo (x shuffled within day) mean is ≤ 0 on every cut. LODO can only lose against a no-op when x carries no signal.
- Name collisions: Grok already excludes off-topic name matches inside its counts (11 rows say "excluded"). No row was left unresolved, so 0 rows were treated as missing.
