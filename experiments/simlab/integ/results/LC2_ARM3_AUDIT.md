# Arm-3 audit re-run on live-code 2 + 12a.5 + writers 12.7 (orchestrator 21:39Z Nov 14)
Files: livecode_2 forecast 3c7da1b5, h25_live ff40d796, input_guard 01547d5b, arm3_live e62eae24 (+ bundle-13 arm3_feats), 12a.5 two_predictions ccb316f9, writers 12.7 (bc381a88). No Gemini.

| night | published 00:05 (model / fallback_used) | parquet published_model | label == acc0(model) | order == published_rank |
|---|---|---|---|---|
| Nov 12, no prewarm | arm3 / null | arm3 | yes (arm 3's own: 56.3/66.3/77.6, 183 d) | yes |
| Nov 13, arm 2 inputs gone | arm3 / null | arm3 | yes | yes |
| Nov 12, arm3 import break | arm2 (arm3 failed) / arm3_failed | arm2 (arm3 failed: ModuleNotFoundError ...) | yes | yes |
| Nov 12, embeddings missing | arm2 (arm3 failed) / arm3_failed | arm2 (arm3 failed: OSError ...) | yes | yes |
| Nov 13, both fail | clean_nosite (arm3 failed) / arm3_failed+clean_nosite_fallback | clean_nosite (arm3 failed ...) | yes | yes |

Findings 1-8: all closed (1, 2, 3 and 8 verified on the runs; 4-7 verified in source: scoreboard reads the model from predictions/<d>_0005.json, conf_top3_shadow / daily weekly score pred_arm3 first, why label from the north-star table, SHAP shadow labelled "arm 2 shadow, not the published model").
Residuals: why_drivers.py:25 SECOND still "58.9 / 69.2 / 74.5" (shadow copy only; table readable_v2 = 51.5/63.5/75.5). Arm-3 label uses final-rank truth and 20 seeds; arm 2's uses the same table. My writers 12.8: prob 0005 uses arm 2's logistic on "arm2 (arm3 failed)" nights (12.7 fell back to the position table).
Timing: embedding 173.7 s with no prewarm (12,231 texts), 5.4 s warm. 03:45 Nov 13 one-id lineup mismatch is pre-existing.
