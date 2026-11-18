# Bundle 13 candidate: forecast input guards (UNDEPLOYED — deploy only on Shreyas's direct word)

Asked by the orchestrator 12:17Z Nov 14 after measuring arm-2 losses with inputs blanked (214 days, top 3):
hunter history -6.7 [-9.3, -4.0], llm_pitch/brand -3.0 [-5.1, -0.8], promo -1.9, busy -1.7, site -0.6.

| file | goes to (VM) | what |
|---|---|---|
| input_guard.py | ~/w/experiments/ph_predict/input_guard.py | new module (store_check, llm_check, coverage, finish) |
| forecast.py | ~/w/experiments/ph_predict/forecast.py | VM 61538501 + 4 guard calls (forecast.py.patch) |
| daily.py.patch | ~/w/experiments/pipeline/daily.py (VM 27f0578d) | forecast step "degraded: ..." on alerts; raw step uploads forecast_inputs_<d>.json and rsyncs data/days to raw/store/days |
| ../20261114_two_predictions/two_predictions.py | bundle 12a | published inputs block gains the guard summary (counts only) |

1. Store: the forecast normally sees day files through d-2 (ranks writes d-1 after the forecast). Any missing day in
   [d-14, d-2] is restored into a persistent overlay (~/w/guard_restore) from raw/store/days (daily copy, new), else the
   newest raw/model_inputs/arm2/<yyyymmdd>/ph_predict_data/days backup; features.D points at the overlay for this run (arm 2
   included). The real store is never written. Recorded in inputs.store_fallback; alert.
2. LLM: pitch/brand checked for every launch (file absent, bad JSON, id absent, NaN). The missing subset is re-scored in a
   scratch dir with backoff 20/60/180 s, total budget 420 s, merged atomically into the day file; still-missing recorded; alert.
   (The line-up only exists at 00:05, so "before 00:05" is impossible; the budget keeps the published file before ~00:20 PT.)
3. promo/busy/site: alert-only when under 50% of today's launches have any input.

Dry test on the VM, 12:22Z Nov 14, scratch copy (3 store days removed, 3 launches' pitch/brand removed), day 2026-11-14:
store restored 3/3 from backup 20261113, overlay 317 days = real 317; llm pitch 0/28 and brand 0/28 missing after 1 retry
(Gemini, 3 launches each); coverage promo/busy/site 100%; alerts: store. Real store and real llm files untouched.
01547d5b2b399271b4ccfa75fa94ad28  input_guard.py
67e8193a99cbc432ef408ced9b244066  forecast.py
a14dbe08f25c6861960a3d020bd98870  daily.py.patch
534555794040cb1b300e02e7ca17c2cb  forecast.py.patch
54f62de68650541662ff9a106fd534e7  ../20261114_two_predictions/two_predictions.py
