# live-code 2 (UNDEPLOYED; orchestrator 21:24Z Nov 14) = live-code 1 + the arm-3 publish switch + E5's arm-3 pre-publish audit fixes
ONE forecast.py: the bundle-13 forecast.py built on 61538501 would revert live-code 1, so it is NOT used. No arm-3 publish line is offered until
E5's arm-3 night audit passes on this build. Needs the today-rows fix (033d7bd7) live first. The PUBLISH file is created separately (deploy_arm3.sh publish).

| file (VM path) | VM now | live-code 2 |
|---|---|---|
| experiments/ph_predict/forecast.py | 61538501 | 3c7da1b5 |
| arm2_live/h25_live.py | e3af37b4 | ff40d796 |
| experiments/pipeline/daily.py | 27f0578d | 54456921 |
| experiments/ph_predict/input_guard.py | (new) | 01547d5b |
| arm3_live/arm3_live.py (only if bundle 13's ~/w/arm3_live exists) | (bundle 13: 09a6a113) | e62eae24 |
| experiments/ph_predict scoreboard.py / conf_top3_shadow.py / why_drivers.py | routine / tw tarball | 0c106894 / 16856bdc / 6a1465c6 (why label from the table ON) |

Audit items:
1. forecast.py: one PUBLISHED name (arm3 / arm2 / clean_nosite) goes into the log, the guard record, REPRO["published"] and a parquet column published_model.
2. 12a.5 (separate folder): the arm-3 label is read from the north-star table row 'arm3'; the fallback constant comes from arm3_backtest_label.txt, now in WANT.
3. PUBLISH on and arm 3 failed: published_model "arm2 (arm3 failed: <reason>)"; 12a.5 writes model "arm2 (arm3 failed)", fallback_used "arm3_failed".
4. scoreboard.py: the model comes from predictions/<d>_0005.json from Nov 14 on (date rule before that).
5. conf_top3_shadow.py: published column first (pred_arm3, then pred_arm2); an arm-3 night is labelled "calibration fit on arm-2 scores".
6. daily.py weekly "launch_model" score: per row, arm 3 if filled, else arm 2, else pred.
7. why_drivers.py: the label comes from the table (readable v2 alone, 51.5 / 63.5 / 75.5, 183 days), and the "2 of 3 shared, 97.7%" claim is dropped.
   On an arm-3 night the SHAP block says "arm 2 shadow, not the published model". In the tw tree, 12.6's tw.sh exports WHY_LABEL_FROM_TABLE=1.
8. arm3_live.py: F.build(include_today=day). Known launches are handled as in live-code 1.
Deploy: `bash ~/w/livecode2.new/deploy_livecode2.sh check|deploy|rollback` (md5 checks, agent only, refuses 23:30-01:00 PT, auto-rollback).
Dry run Nov 14 (dry_livecode2.sh, scratch trees, features 033d7bd7):
- B (no PUBLISH): published_model arm2, order = arm 2's, top 10 = current code's 10, repro "arm2".
- C (PUBLISH + arm3_live): published_model arm3, order = arm 3's, pred_arm2 kept, top-10 overlap with current 9, repro "arm3".
- D (PUBLISH + failing arm3_live): published_model "arm2 (arm3 failed: arm3 error RuntimeError: forced ...)", order = arm 2's.
- 12a.5's midnight writer on C / D: model arm3 with the table arm-3 label / model "arm2 (arm3 failed)" with fallback_used arm3_failed;
  ranking = published_rank in both. The real llm_* dirs were not modified.
