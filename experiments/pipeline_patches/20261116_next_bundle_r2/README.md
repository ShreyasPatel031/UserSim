# Next bundle (20261115). NOT DEPLOYED: it deploys only on Shreyas's word.

**r2 (Nov 16):** copy of 20261115_next_bundle (deployed Nov 16 ~04:20Z) with two changes. (1) `deploy_nb.sh` f400bafa: check mode now mirrors the installed `tw/experiments/pipeline` package, so the false FAIL of Nov 16 (comment_forecast: no module pipeline) no longer happens. (2) `run_chain.sh` 3dd99cc1: runs `check` and deploys only when it passes, with no pipe around the check. Deploy through `bash run_chain.sh deploy_h25|deploy`.

Modes of `deploy_nb.sh`:
- `check`: read-only. Mirrors the installed dirs, or this bundle's base_12_8/ copies where 12.8 or arm3 are not installed, applies every overlay, and runs the import gates.
- `deploy_h25`: arm 2 only, tonight's fix. rootlink.py and h25_live into ~/w/arm2_live. Needs no 12.8.
- `deploy`: everything below; needs bundle 12.8 (~/w/tw).
- `rollback`: restores from ~/w/nb_backup/map.txt and removes the files it created.
Every replaced file must have its expected base md5 or nothing changes. The 23:30-01:00 PT refusal applies to both deploy modes.

| file | md5 | destination | why |
|---|---|---|---|
| rootlink.py | 38e37fba | ~/w/arm2_live, ~/w/tw/h25, ~/w/tw/experiments/ph_predict, ~/w/arm3_live | one shared private-root builder: links new files into real llm_* dirs, relinks broken links, never crashes on them |
| h25_live.py | 2f49972b | ~/w/arm2_live (over live-code 2's ff40d796) | uses rootlink: llm_pitch / llm_brand were null for every launch from Nov 14 |
| h25_live_cur.py | 364b3b2a | ~/w/arm2_live (over the deployed e3af37b4) | the same fix, when step 5 has not run |
| arm3_live.py | 52ba59d5 | ~/w/arm3_live (over e62eae24 only) | uses rootlink (same bug in ~/w/h25/data_arm3) |
| h25_shadow.py, history_retrain.py | d215f867, 4f3dbc1c | ~/w/tw/h25 (over 12.8's 7d9ec545, a3f9de9b) | use rootlink |
| comment_forecast.py | b17ce67a | ~/w/tw/experiments/ph_predict (over ef9264a1) | cached comment dumps, honest_preds and forecast_<d>.parquet re-downloaded when the bucket copy is newer (a 00:05 rerun now reaches the 03:45 lines) |
| tw.sh | e1e6c8c1 | ~/w/tw/tw.sh (over 422f1396) | a failed warehouse sync is logged plus an alert file results/timed_writes/alerts/<d>_sync_wh_<HHMM>.txt |
| readable_shadow.py | 2851a666 | ~/w/tw/h25 (over c26c69be) | per-launch raw "values"; ph_n_makers == 0 -> missing |
| arm2_shap.py | 92f9e80d | ~/w/tw/experiments/ph_predict (over bd0ae425) | arm 2 TreeSHAP + per_input_centred + raw values |
| ctrl.py | b47fc28f | ~/w/arm2_live | tracked copy of the hand-added file |
| base_12_8/* | (12.8 / live-code 2 bases) | check mode only | lets the check run while 12.8 / arm 3 are not installed |

Order: DEPLOY_ORDER steps 1-6, then `deploy`. For tonight's arm-2 fix alone: step 1 + `deploy_h25` (optionally after step 5; if deploy_h25 runs
first, step 5 will refuse because it expects e3af37b4; then run step 5 and deploy_h25 again, which picks h25_live.py).

## b12a6/ (the before-reveal writer, as a new named 12a build; deploy with `bash b12a6/deploy_b12a.sh <path>/b12a6`, atomic flip, instead of 12a.5)
12a.5's files with two_predictions.py 3388bd96 (WANT updated in deploy_b12a.sh 2621d21e). The 03:45 accuracy label and its top-10 edge over the hidden order
are read from north_star_table.json (prereveal rows now carry edge_vs_hidden, paired, day bootstrap). The row is the fixed-prior one only when
~/w/today_rows_fix.json exists (step 1 deployed); otherwise the live-prior one (+5.8 [+0.8, +10.8]). The build-constant fallback names both edges.

## Arm-2 input null check (orchestrator 08:22Z Nov 15)
h25_live (2f49972b / 364b3b2a) writes the null rate of every arm-2 input, from the rows fed to the boosters, to data/arm2_input_nulls/<d>.json
and raw/daily/<d>/arm2_input_nulls_<d>.json (best effort; never raises). It also writes hist_hunter_rel|has_history (0 in the backtest).
The 12a.6 writer (b12a6/two_predictions.py 06ad5350 + arm2_backtest_nulls.json c9207a34) lists every input more than 10 points above its
backtest null rate under inputs.missing in the published 00:05 file, and writes results/timed_writes/alerts/<d>_arm2_inputs_<HHMM>.txt.
On Nov 14's live rates it would list hist_hunter_rel, hist_hunter_rel|has_history, llm_brand and llm_pitch.
