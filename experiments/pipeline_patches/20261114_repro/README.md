# 20261114_repro — reproducible 00:05 fit (UNDEPLOYED)

Orchestrator 15:47Z Nov 14. Needs Shreyas's direct word before it goes onto the VM. New named build. The verified bundle folders are not changed.

| File | What |
|---|---|
| h25_live.py / h25_live_repro.patch | arm 2 (VM arm2_live/h25_live.py e3af37b4 → 0bac177f): (day, id) stable sort before fit, `deterministic=True, force_row_wise=True, n_jobs=REPRO_JOBS` (4), `REPRO_SEEDS` (5; 20 tested, no gain), info adds seeds, sha_train, sha_test (sha256 of the input frame, 16 chars) and library versions |
| forecast.py / forecast_repro.patch | clean_nosite fit (VM 61538501): same four changes; writes results/forecast_repro_<d>.json with {clean_nosite, arm2, versions, published} |
| tie_note.py / why_drivers_tie.patch | why file `items.tie_note` when picks 3/4, 5/6 or 10/11 are within 0.019 log-votes of each other (the score of the model that was published), with the measured 51% vs 59% top 3 |

Overlaps: forecast.py is also patched by 20261114_input_guards (store restore and llm retry, top of file) and 20261114_arm3_shadow
(PUBLISH switch, after the arm-2 block). The hunks don't touch the same lines. Apply in this order: input_guards → arm3_shadow → repro.
`patch --dry-run` each one on the VM copy first.

20 seeds vs 5 (paired, history_retrain JOINT harness, results/history_retrain_joint_arm2_s20.parquet vs decomp 'both'):
- >= 10 ranked (183 d): 5 seeds 58.1 / 65.2 / 76.9, 20 seeds 57.4 / 65.2 / 76.8; diff top 3 -0.7 [-1.6, +0.0], top 5 +0.0 [-0.5, +0.7], top 10 -0.1 [-0.4, +0.2]
- all 214: top 3 -0.8 [-1.6, +0.0]; last 90: top 3 +0.0 [-1.1, +1.1]
No gain, so the default is 5 seeds (REPRO_SEEDS=5). The published backtest figures (58.1 / 65.2 / 76.9) are 5-seed figures.
Reproducibility comes from the sort and the deterministic flags, not from the seed count. Runtime is unchanged.
