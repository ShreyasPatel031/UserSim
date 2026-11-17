# Arm-3 live vs backtest parity (arm 2 as control): no bug moves a top-10 pick

Orchestrator request 10:44Z Nov 17. Scripts: `parity.py` (the run) and `train_rows_check.py`. Output: `parity_summary.json`. Per-launch rows are in the scratchpad only. Counts and launch ids only.

## Paths compared

**Live published**
- `raw/daily/<d>/forecast_<d>.parquet`: `pred_arm3` (Nov 17, first published) and `pred_arm2`.
- `results/shadow_arm3/2026-11-16.json` for the Nov 16 shadow.
- **Not available:** the live per-launch input matrix for arm 3. Only `arm2_input_nulls_<d>.json` (null rates) and five inputs in the parquet are written.

**Live replay**
- The deployed code (bundle r5: `arm3_live.predict`, `h25_live.predict`) copied verbatim, so it also returns its inputs.
- Run on the VM's input snapshot `raw/model_inputs/arm2/20261116`, taken 22:30 PT Nov 16.
- The file set matches what the VM held at 00:05 on d:
  - finished day files through d−2 (`forecast_inputs` store.latest_day = d−2);
  - the 2025 lists;
  - only d's 00:05 line-up in `today/`.

**Backtest path (E5 rebuild)**
- `history_retrain.build` over day files, then `TW.prep`, then the `e5_abc.py` A/B/C code.
- Same training cutoff as live (days ≤ d−2). Training B/C come from the stored rebuild table; 5 seeds.
- The rows for day d are:
  - Nov 14–15: the re-read day file (the rebuild's own condition);
  - Nov 16–17: the 00:18 PT read, because the snapshot has no re-read for those days.

**Same columns.** Both paths use the same 62 inputs: 40 arm-2 inputs plus 22 A/B/C. Nov 17's replay lacks that night's `llm_pitch`, `llm_brand`, `busy_*` inputs, because they were scored on the VM after the snapshot was taken.

## Results

Spearman / top-10 overlap / top-3 overlap, then hit rates at top 3 / 5 / 10.

| day | published vs live replay | live replay vs backtest | published vs backtest | arm-2 control: published vs replay |
|---|---|---|---|---|
| Nov 14 | — (shadow not written) | 0.957 / 10 / 2 | — | 0.920 / 8 / 2 (pre-fix night; see below) |
| Nov 15 | — | 0.957 / 9 / 2 | — | 0.896 / 10 / 3 |
| **Nov 16 (shadow)** | **0.996 / 10 / 3** | 0.998 / 10 / 3 | 0.996 / 10 / 3 | 0.989 / 10 / 3 |
| **Nov 17 (published)** | **0.960 / 10 / 2** (replay without that night's LLM/busy) | 0.992 / 9 / 2 | 0.952 / 9 / 3 | 0.924 / 10 / 2 |

Hit rates (top 3 / 5 / 10):
- **Nov 16:** published arm 3 67 / 40 / 60; replay and backtest are identical.
- **Nov 17:** published arm 3 0 / 0 / 50; backtest 0 / 0 / 60.

## Column-by-column

**No null-rate flags.** No input has a null rate above 5% on one path and not the other, on any day. Hunter-history null rates are equal on both paths on every day; for example, `hist_hunter_rel` is 50% / 50% on Nov 16 and 55.8% / 55.8% on Nov 17.

**Mismatching columns on every day are tiny.**
- Inputs fitted on the training rows: `txt_ridge`, `topic_prior_*`, `comp_nn_*`. Live vs backtest correlation is 0.96–1.00, and the median difference is under 3% of the column's spread.
- The training rows are identical: 12,280 rows (5,208 from 2025) on both paths, with the same ids.
- The difference comes from row order. `add_fold_feats` assigns its 4 out-of-fold folds by `factorize(tr.day) % 4`, so a different row order gives different folds. A few pitch texts also differ ("nan" vs "").
- `hist_hunter_n / rel / top5` differ on 4–5 launches a day, with equal null rates.

**Nov 14–15 only: real data drift, not code.** The backtest uses the later re-read of the day; live sees the 00:05 state.
- Makers added after 00:05: `ph_dayrank_ph_n_makers` correlation 0.94 on Nov 14.
- Descriptions edited: `A_cos_mean` correlation 0.98–0.99.
- Launches added: Nov 15 has 16 launches in the re-read vs 15 at 00:05, which shifts `ph_day_n_launches` and the A crowding inputs.

## Swap test

Each mismatching column was put into the live row one at a time, using its backtest value, and the live model re-predicted.

| day | columns that moved a pick | why (by design or near-tie) |
|---|---|---|
| Nov 16 | **none** | |
| Nov 17 | `comp_nn_mean`: one top-3 change, no top-10 change | near-tie |
| Nov 15 | `A_fol_pct_in_topic`: one top-10 change | line-up added after 00:05 (by design) |
| Nov 15 | `B_nn10_wlogv`, `hist_dayrank_hist_hunter_rel`, `ph_name_len`: one top-3 change each | text or name edited after 00:05 |
| Nov 14 | `txt_ridge`, `comp_nn_mean`: one top-10 change each | fold-order noise on near-ties |
| Nov 14 | `ph_n_makers`, `ph_dayrank_ph_n_makers`: one top-3 change | maker added after 00:05 |

## Verdict

**No code bug.**
- **Deployed arm 3 is reproduced.** The live code replayed on the VM's own inputs gives the published arm-3 order: Nov 16 shadow 0.996 with the same top 10; Nov 17 0.960 with the same top 10, even without that night's LLM and busy inputs.
- **Backtest path matches.** It gives the same top 10 as published on Nov 16, and 9 of 10 on Nov 17.
- **No input is missing or nulled on one path only.**

Nothing to hand to the PH agent as a bug fix. There are two non-bug items:

1. **Logging gap (recommended, small).**
   - **Problem:** live arm 3 writes no per-launch input record, so this audit had to replay from a snapshot.
   - **Fix:** after `arm3_live.py` builds `te[cc]` (just before the 5-seed fit), have the VM write `raw/daily/<d>/arm3_inputs_<d>.parquet` (id + the 62 inputs) and `arm3_input_nulls_<d>.json`. Launch ids and counts only.
   - **Effect:** none on the forecast; future parity checks become a direct diff.
2. **Backtest optimism from the re-read, measured on only 2 days.**
   - **Problem:** the backtest scores day d on the later re-read (final line-up, edited text, added makers); live sees 00:05.
   - **Size:** on Nov 14–15, backtest arm 3 scored 67 / 80 / 60 and 100 / 60 / 70, against 33 / 80 / 60 and 67 / 60 / 70 for the live replay. It is about +33 at top 3 on both days. With 2 days this is not a measurement.
   - **Already being addressed:** this is the known re-read vs 00:05 issue (the earlier "today/ stale-rows" work, and the 6% line-up-drop robustness rows in `e5_abc`). The 00:05-view rebuild (`e5_asof_0005.py` / `asof3`) is the right backtest for published numbers.

**Arm-2 control: same picture.**
- Nov 15–17: replay vs published is 0.90–0.99 with 10 of 10 the same in the top 10.
- Nov 14 is 0.920 with 8 of 10. It was a pre-fix night: the stale today/ rows bug, fixed from Nov 14 evening.
