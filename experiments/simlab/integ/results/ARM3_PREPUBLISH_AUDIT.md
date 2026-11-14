# Arm-3 pre-publish audit (orchestrator 20:48Z Nov 14)
Chain: live-code 1 + bundle-13 PUBLISH switch hunk merged as written; 12a.3 two_predictions bcbaf6b6; writers 12.5 (c01927d0) and 12.6; no Gemini.
Nights: n12 (no prewarm), n13 fallback (arm 2 inputs removed), n12 arm3 import break, n12 embeddings missing, n13 both fail. Reports: arm3pub_*.json.

| night | arm 3 | published 00:05 | label | order == published_rank |
|---|---|---|---|---|
| Nov 12 | published (embed 222.5 s, 12231 texts) | arm3 | "arm 3 (backtest label not set)" | yes |
| Nov 13 arm2 inputs gone | published (embed 5.2 s, cache warm) | arm3 | "arm 3 (backtest label not set)" | yes |
| Nov 12 import break | ModuleNotFoundError arm3_feats | arm2, fallback_used null | arm 2 58.0/65.2/76.5 | yes |
| Nov 12 no embeddings | OSError (HF offline, no cache) | arm2, fallback_used null | arm 2 | yes |
| Nov 13 both fail | import break + arm2 0 train rows | clean_nosite, clean_nosite_fallback | 54.3/64.7/75.7 | yes |

## Findings (file:line, smallest fix)
1. live-code 1 forecast.py:65 and :67 (merged file :80/:82) record G.STATE["published_model"] and REPRO["published"] = ARM2 when arm 3 published (forecast_inputs says "arm2 published"). Fix: set both to ARM3 when it starts "arm3 published". Also: live-code 1 has no switch at all; bundle-13 forecast.py is built on 61538501 and would revert live-code 1 -> ship one combined file.
2. 12a.3 two_predictions.py:24 ACC3 reads arm3_backtest_label.txt, absent and not in deploy WANT -> published label "arm 3 (backtest label not set)" on both arm-3 nights. Fix: ship the file (or ACC0_BY["arm3"]) with arm 3's restated figure.
3. 12a.3 two_predictions.py:88 fallback_used null when PUBLISH exists but arm 3 failed -> silent arm 3 -> arm 2 substitution. Fix: fallback_used "arm2 (arm3 failed)" when ~/w/arm3_live/PUBLISH exists and pred_arm3 not complete.
4. scoreboard.py:162 attributes the model by date ("arm 2" from Nov 15). Fix: read model from predictions/<d>_0005.json.
5. conf_top3_shadow.py:24/34 scores pred_arm2 but labels it "published 00:05 order". Fix: pred_arm3 first when complete.
6. live-code 1 daily.py:463 weekly launch_model scores pred_arm2. Fix: pred_arm3 first when complete.
7. why_drivers.py:13 "shares 2 of 3 top picks with the forecast on 97.7% of days" measured vs the old forecast; arm2_shap describes arm 2 (shadow only). Fix: drop the overlap claim or recompute vs the published model; label SHAP "arm 2 (shadow), not the published model" on arm-3 nights.
8. arm3_live uses include_today=True (newest today file), not the explicit day. Fix: pass the day.
9. (mine, FIXED in 12.6) prob_writer parquet fallback took pred_arm2 + arm-2 logistic on an arm-3 night (reproduced with 12.5). 12.6: pred_arm3 position table + arm-3 note.
10. (mine, FIXED in 12.6) track record live line pooled models; now per-model lines + warning.

Correct already: web_forecast_0005 uses published_rank; prob 0005 via predictions file names arm3 and uses the position table (no arm-2 logistic); weekly entrants use pred_arm3 with "approximate" calibration note; arm 2 kept as shadow column on every arm-3 night; 03:45 file unaffected (Nov 13 one-id lineup mismatch is pre-existing, same in non-arm-3 run).
Timing (4-thread container, file mtimes, approx): forecast step ~7.5 min Nov 12 no prewarm, ~2.7 min Nov 13 warm cache -> fits 00:05-00:20; no prewarm costs ~3.7 min embedding.
