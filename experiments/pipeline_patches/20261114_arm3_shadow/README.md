# Bundle 13: arm 3 (UNDEPLOYED; shadow step and publish step each need Shreyas's direct word)

Arm 3 = arm 2 + E5's 00:05 block (same-day crowding, novelty/retrieval vs past launches with bge-small, relaunch). Top 10 replicated three
times (orchestrator subagent +1.2, E5 +1.9 [+0.9, +2.8] on 183 days, untouched 2025 days +1.0) and in PH ops' own JOINT harness
+1.1 [+0.2, +2.1] (183 days; top 3 -0.9 [-2.7, +1.1], top 5 +1.1 [-0.3, +2.5]).

Step 1 SHADOW (no change to the published file):
- `deploy_arm3.sh install <this folder>`: E5's pinned modules (arm3_feats.py, arm3_live.py, test_arm3_feats.py) + arm3_shadow_run.py +
  import_gate.py -> ~/w/arm3_live (history_retrain / ctrl / honest copied from ~/w/arm2_live); gates: bge-small loads OFFLINE at revision
  5c38ec7c (already cached on the VM), E5's tests pass, imports as the shadow job runs them; cache prewarm (~6.5 min, 11,968 launches).
- bundle 12 jobs: `arm3_shadow` 01:21 PT (+ catch-ups) -> ~/w/arm3_live/results/<d>.json + gs://.../results/shadow_arm3/<d>.json with
  pred_arm3, its rank and the published rank; `arm3_prewarm` 22:40 PT embeds finished days so 00:05/01:21 embed only the line-up.
Step 2 PUBLISH (separate switch): `forecast.py` = VM 61538501 + forecast_publish_switch.patch: if ~/w/arm3_live/PUBLISH exists, the 00:05
  order = pred_arm3, arm 2 stays as pred_arm2; any arm-3 failure keeps arm 2 and says why; without the file nothing changes (no new
  parquet column). `deploy_arm3.sh publish` gates and creates the file; `unpublish` / `rollback` are always allowed.
  two_predictions.py (bundle 12a.1, ../20261114_two_predictions_12a1/) publishes pred_arm3 when present with model "arm3" and the label from arm3_backtest_label.txt.
  NOTE: forecast.py is also changed by the input-guards bundle (20261114_input_guards); deploy one combined file.

VM dry run 14:40Z Nov 14 (scratch dir, DRY=1): offline model ok; E5 tests pass; gate 23 imports ok; prewarm 11,968 launches 390 s.
Shadow run FAILED with E5's 51be2722 ("Input y contains NaN": past days' 00:05 line-up files enter training); with the one-line fix
(((day < d) & ~is_today) | today rows) it ran ok: 28 launches, 62 inputs, 85 s. Waiting for E5's fixed commit before pinning.
8cfe9192  arm3_feats.py
ad2fab6a  arm3_live.py
29d6809e  arm3_shadow_run.py
f69b20bf  forecast.py
be4891b9  import_gate.py
1a418cbf  test_arm3_feats.py
87bcb92e  deploy_arm3.sh
0fd0ae25  forecast_publish_switch.patch
