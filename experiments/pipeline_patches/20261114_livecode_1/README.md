# live-code 1 (UNDEPLOYED; orchestrator 18:42Z Nov 14). One build for the live 00:05 path; arm-3 publish/shadow pieces stay separate.
Needs Shreyas's direct word. E5 reviews it before it is recommended.
Prerequisite: the today-rows fix (features.py 033d7bd7, its own one-file line) must be live first. Live-code 1 passes the day explicitly, and the
old features.py treats any truthy value as "all today files".

| file (VM path) | VM now | live-code 1 | carries |
|---|---|---|---|
| experiments/ph_predict/forecast.py | 61538501 | 4eabc2af | input guards; explicit-day build + clean exit on a missing line-up; known launches kept in the line-up (LLM inputs blank, train-only drop, .md note, parquet `known`); repro (stable sort, deterministic row-wise LightGBM, n_jobs 4, 5 seeds, results/forecast_repro_<d>.json with sha256 + versions); parquet `published_rank` |
| arm2_live/h25_live.py | e3af37b4 | ff40d796 | repro; explicit-day build; known launches kept |
| experiments/pipeline/daily.py | 27f0578d | 2b0f4c97 | input guards (degraded step, inputs file upload, raw/store/days rsync); forecasts table ids from the parquet; weekly "launch_model" score reads the published column (pred_arm2 when filled) |
| experiments/ph_predict/input_guard.py | (new) | 01547d5b | guards module (bundle 13) |

Combined diffs against the VM files: forecast.patch, h25_live.patch, daily.patch.
Deploy: `bash ~/w/livecode1.new/deploy_livecode1.sh check|deploy|rollback`. It checks md5s, refuses 00:05-01:00 PT and requires features.py 033d7bd7.
It backs up the three files and installs all four atomically, then runs the import gate on forecast.py, h25_live.py and pipeline.daily.
Any failure rolls back. Rollback restores the three files and removes input_guard.py.

Dry run (dry_livecode.sh, Nov 14 ~20:20Z, VM scratch trees, both on features 033d7bd7; A = current code, B = live-code 1):
- both rc 0; both published arm 2 (656 train days, 4,923 rows from 2025, 40 inputs).
- B vs A order: top 3 identical, the same 10 launches in the top 10; the order first differs at #6. That comes from the repro changes (stable
  sort, deterministic row-wise LightGBM). No guard fired; 0 known launches. B re-run: bit-identical parquet.
- B's forecast_repro_<d>.json carries sha_train / sha_test and versions for both models; forecast_inputs_<d>.json shows store 0 missing,
  pitch / brand 0 missing, coverage 100%.
- Missing line-up (day 2099-01-01): exits 1 with "no line-up for 2099-01-01: data/today/2099-01-01.json missing or empty", and no forecast files.
  The store guard first alerts on the missing days, as expected for a far-future day.
- The real llm_* dirs were not modified during the runs.
- E5's check (20:43Z): on Nov 12 the repro hunk changes the order from #2 (top-10 overlap 9), i.e. at the measured run-to-run noise level.
  Without the repro hunk, live-code 1 equals the current code exactly.
- Not exercised by data: a known launch (0 in 2026 live nights; 1 in all of 2026). The code path is the same column blanking as h25_live's
  old-row rule.
