# 20261114_today_rows — stale today/ rows in F.build(include_today=True) (UNDEPLOYED)

Bug (orchestrator report 16:10Z Nov 14, confirmed read-only on the VM): `data/today/` keeps every night's line-up file (18 on Nov 14: Oct 25 – Nov 4,
Nov 8 – 14). `F.build(include_today=True)` read all of them, so 425 unlabelled rows (votes and rank NaN) entered `add_history` and the same-day
counts. Nov 14, both the 2026 build (forecast.py clean_nosite) and h25_live (arm 2):
- test day: 7 of 11 launches whose hunter has earlier launches got `hist_hunter_rel` NaN; `hist_hunter_n` and `hist_hunter_top5` wrong on 7; `hist_maker_n` on 4;
- training rows Oct 25 – Nov 13: rel NaN on 145, top5 on 136, maker_n on 186, `ph_hunter_n_same_day` doubled on 423.
Every include_today=True caller shares features.build: forecast.py, ~/w/arm2_live/h25_live.py, ~/w/h25/{h25_live,h25_shadow,readable_shadow,forecast_arm2}.py,
clean_live.py, makerfix_shadow.py, forecast_week.py, sim_forecast.py, data/shadow/e1v2/predict.py, E5's arm3_live.py. ~/w/fa/features.py is a separate copy (not patched here).

Fix (features.py 981c5ded → 033d7bd7, features_today_rows.patch, 3 hunks):
1. build reads only the target day's today file: include_today=True → newest today/ file; a 'YYYY-MM-DD' string → that day; skipped if days/ already has it.
2. a today row whose id is also in a labelled day is dropped.
3. add_history never appends an unlabelled row (is_today or NaN votes). On the VM no labelled row has NaN votes (0), so labelled history is unchanged.

Test: test_today_rows.py (live-style frame from the real data dir with all 18 today files). Current 981c5ded: FAIL on all three checks
(425 stale today rows; 7 of 11 rel NaN; 423 same-day counts). Patched: PASS (28 today rows = the test day).
arm2_diff.py: Nov 14 arm-2 order with current vs fixed features (scratch roots only).

Missing line-up (orchestrator 16:35Z): the callers now pass the day, include_today=day (forecast.py 61538501 -> 2641e01b, forecast_today_day.patch;
arm2_live/h25_live.py e3af37b4 -> 9ed1c7c4, h25_live_today_day.patch). If data/today/<d>.json is missing, the build has no today rows.
- forecast.py exits non-zero before the LLM step: "no line-up for <d>". No forecast_<d> file is written, so two_predictions reports none_available.
- h25_live: the test set is empty, so it raises RuntimeError and forecast.py falls back (it also stops on the line above).
Even before this change, rows keep their own file date, and both callers select day == d. So a missing line-up never ranked yesterday's line-up as today's;
it gave an empty test set (old code: forecast.py failed later in the fit). Test check 4 (d2 = 2026-11-15, no file): the explicit-day build has
0 today rows, and the newest-file build has 0 rows dated d2. PASS.
Overlap: forecast.py is also patched by input_guards, arm3_shadow and repro; this hunk is line 10 only.

Deploy: copy features.py to ~/w/experiments/ph_predict/ (h25_live imports it from there). Needs Shreyas's direct word.
Overlap: no other undeployed bundle patches features.py.
