# Arm-2 null-input audit (orchestrator 00:57Z Nov 15). Read-only VM runs, scratch copies of arm 2's data root only.

| input | live 00:05 build (deployed code, Nov 12-14) | backtest rows (X.parquet, Apr-Oct) |
|---|---|---|
| llm_pitch, llm_brand | null for 100% of Nov 14 launches (and of every new day) | ~0% null (0.1% / 1.2%) |
| hist_hunter_rel, hist_dayrank_hist_hunter_rel | null 86% / 100% / 86% (Nov 12 / 13 / 14) incl. hunters with history (e.g. 558 earlier launches) | null only with no history (52.9%; 0.0% when hist_hunter_n > 0) |
| hist_hunter_top5 | 40-61% (= no history) | 52.9% (= no history) |
| other inputs | no nulls beyond the backtest's | promo_* 1.2% |

Causes:
(a) llm_pitch / llm_brand: arm 2 reads a private root ~/w/h25/data in which llm_pitch_gemini and llm_brand_gemini are REAL directories (2025 scores
    + per-file links to the 2026 files made once at Nov 13 10:47Z). Gemini scoring itself works: data/llm_pitch_gemini/2026-11-14.json holds all
    28 launches (written 08:13Z). Arm 2 never sees a new day's file. This is not the DataImpulse/Gemini errors.
(b) hist_hunter_rel: features.py 981c5ded (deployed) reads all 18 data/today files, so stale unlabelled rows (votes NaN) enter add_history. The mean
    of the hunter's earlier relative votes is then NaN. In the example, 19 of 558 earlier rows are today rows of Oct 25 - Nov 12.
    This is the today-rows bug. With features.py 033d7bd7 (DEPLOY_ORDER step 1), Nov 14 hist_hunter_rel nulls = hist_hunter_top5 nulls (no history only).
Fix check (scratch root): with the llm-link fix, llm_pitch / llm_brand are non-null for 28 of 28.
Impact on Nov 14 (both fixes vs deployed code, same 5 seeds): Spearman 0.911; top 3 overlap 2 of 3; top 5 5 of 5; top 10 8 of 10; same #1.
