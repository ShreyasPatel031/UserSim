"""Near-tie tie-breaking for arm 2 (orchestrator 19:16Z Nov 14). One script, two stages, no LLM calls.
PREDICT (this file): month-forward, rows sorted by (day, id), 10 seeds (0-9) pooled.
  2025 test months 2025-03..2025-12 (train: 2025 rows of earlier months; selection stage)
  2026 test months 2026-04..2026-10 (train: every row of earlier months incl. 2025; test stage)
  scores per test row: arm2 (deployed recipe: TW.prep cols minus ID_COLS / llm_site / ph_month), arm2 per-seed sd,
  arm3 (arm2 + arm3_feats strong), clean_nosite (= arm 2's features trained on the test year's rows only; in 2025 that IS arm 2, so it
  cannot be chosen there), readable (additive depth-1 stumps on the 10 readable-v2 inputs, monotone signs from training correlation),
  raw hist_hunter_rel and llm_pitch.
Scoring / selection / test: score_tiebreak.py.      usage: python e5_tiebreak.py <out parquet>"""
import json, os, sys, time
os.environ.setdefault("LGB_THREADS", "4")
import numpy as np, pandas as pd, lightgbm as lgb
import history_retrain as HR, training_window as TW, arm3_feats as A3
t0 = time.time(); OUT = sys.argv[1]; SEEDS = range(10)
df, _ = HR.build(os.environ["H25_SRC"]); df = df.reset_index(drop=True)
E = np.load(os.environ["EMB"]); assert len(E) == len(df)
X, NEW = A3.add_feats(df, E, norm="strong"); X["id"] = X.id.astype(str)
X = X.sort_values(["day", "id"]).reset_index(drop=True)
RD = ["hist_hunter_rel", "hist_hunter_n", "hist_hunter_top5", "llm_pitch", "topic_prior_mean", "txt_ridge", "ph_n_media", "ph_n_makers", "ph_hunter_age_d", "promo_cov"]
P = dict(TW.P0, n_jobs=int(os.environ["LGB_THREADS"]))
def fit(tr, te, cols, seeds=SEEDS, **kw):
    ps = np.array([lgb.LGBMRegressor(random_state=s, **{**P, **kw}).fit(tr[cols], tr.logv).predict(te[cols]) for s in seeds]); return ps.mean(0), ps.std(0)
months = [f"2025-{m:02d}" for m in range(3, 13)] + [f"2026-{m:02d}" for m in range(4, 11)]
rows = []
for m in months:
    yr = m[:4]; te0 = X[X.mon == m]
    if not len(te0): continue
    tr0 = X[(X.mon < m) & (X.day >= "2025-01-01")]
    tr, te, cols = TW.prep(tr0, te0); base = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    tr = tr.sort_values(["day", "id"]); te = te.sort_values(["day", "id"])
    o = te[["id", "day", "dailyRank", "hist_hunter_rel", "llm_pitch"]].copy(); o["year"] = yr
    o["arm2"], o["arm2_sd"] = fit(tr, te, base)
    o["arm3"], _ = fit(tr, te, base + NEW)
    if yr == "2026":
        trc = tr[tr.day >= "2026-01-01"]; o["clean_nosite"], _ = fit(trc, te, base)
    else: o["clean_nosite"] = np.nan
    rd = [c for c in RD if c in tr]; sg = [int(np.sign(np.nan_to_num(tr[c].corr(tr.logv))) or 1) for c in rd]
    o["readable"], _ = fit(tr, te, rd, seeds=range(5), max_depth=1, num_leaves=2, monotone_constraints=sg, colsample_bytree=1.0)
    rows.append(o); print(json.dumps({"month": m, "n_test": len(te), "s": round(time.time() - t0)}), flush=True)
pd.concat(rows).to_parquet(OUT); print("done", flush=True)
