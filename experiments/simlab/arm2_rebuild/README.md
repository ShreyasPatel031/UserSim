# Arm 2 rebuild from the bucket backup (E5, Nov 14)

**Source.** gs://…/raw/model_inputs/arm2/20261113/: ph_predict_data, code/, and h25_llm/ (the 2025 llm_pitch / llm_brand Gemini scores). Plus raw/ph_history/2025 (365 days).

**What was missing at the start, all added by PH ops at 11:56Z:**
1. The 2025 Gemini llm_pitch / llm_brand scores. These are the only difference between arm 2 and arm 1.
2. The pipeline modules features.py, model.py, training_window.py, run.py, llm.py and buildcache.py. The VM's features.py and llm.py differ from the branch.

**Nothing was guessed.**

**Run.** `ARM=2 DECOMP=1 DECOMP_TAG=_rb DECOMP_MONTHS=2026-04..2026-10 SEEDS=5 python history_retrain.py`, with the backup's code and the backup data as features.D.

**Result, 214 days (Apr–Oct).**

| | top 3 / 5 / 10 |
|---|---|
| both (arm 2), rebuilt | 59.3 / 68.2 / 75.5 |
| both (arm 2), reference | 60.7 / 68.4 / 75.7 |
| pure, rebuilt | 56.2 / 67.4 / 74.8 |
| pure, reference | 56.9 / 67.6 / 75.0 |

Paired against the reference: both −1.4 [−3.0, 0.0] / −0.2 / −0.2; pure −0.6 [−1.4, 0.0]. The prediction correlation with the reference is 0.997. The reference was run on Nov 13 11:24 with 339 days of 2025 lists. The backup holds 365, and its feature files are 12 hours later. The 2026-only (pure) line also drifts, so data drift explains the gap, not a missing piece.

Arm 2 minus pure, rebuilt: top 3 +3.1 [+0.5, +5.6]; last 107 days +3.7 [+0.3, +7.2].

**Label tests.** Results are in labels_score.json, produced by e5_a2_labels.py with 5 seeds and a paired day bootstrap.

## LLM score noise, no-call version (Nov 14)
No new Gemini calls were made; the call was blocked by a permission check.

**retest_pairs.py → retest_pairs.json.** Stored pairs only:
- Relaunches of the same product name (n 398). Their text and lineup differ, so this is an upper bound on noise, not test-retest.
- Claude vs Gemini on the same launch (inter-model).

**e5_llm_noise.py → noise_score.json.** Gaussian noise is added to the test rows' llm_pitch / llm_brand in the arm-2 rebuild, with the models fixed. 3 draws × 5 seeds; the result is the change in top 3 / 5 / 10 with a paired day bootstrap.
