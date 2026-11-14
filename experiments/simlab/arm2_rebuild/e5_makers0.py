"""arm 2 with ph_n_makers = 0 -> NaN (pre-registered: results_reports/PREREG_makers0_nan.md, commit c870147e). No LLM calls.
Same harness as e5_tiebreak.py: month-forward, rows sorted by (day, id), deployed column set, TW.P0 params, 5 seeds (0-4) averaged.
  2025 test months 2025-03..2025-12, 2026 test months 2026-04..2026-10; train = rows of earlier months from 2025-01-01.
Columns: arm2 (as is) and fix (ph_n_makers NaN where the maker list is empty; ph_dayrank_ph_n_makers recomputed within the day on the
non-missing launches only; the same change applied to train and test rows).
    usage: python e5_makers0.py <out parquet>"""
import json, os, sys, time
os.environ.setdefault("LGB_THREADS", "4")
import numpy as np, pandas as pd, lightgbm as lgb
import history_retrain as HR, training_window as TW
t0 = time.time(); OUT = sys.argv[1]; SEEDS = range(5)
df, _ = HR.build(os.environ["H25_SRC"]); X = df.reset_index(drop=True); X["id"] = X.id.astype(str)
X = X.sort_values(["day", "id"]).reset_index(drop=True)
Xf = X.copy(); zero = Xf.ph_n_makers == 0
Xf.loc[zero, "ph_n_makers"] = np.nan
if "ph_dayrank_ph_n_makers" in Xf:
    Xf["ph_dayrank_ph_n_makers"] = Xf.groupby("day").ph_n_makers.rank(pct=True)
print(json.dumps({"rows": len(X), "zero_makers": int(zero.sum()), "zero_2025": int((zero & (X.day < "2026-01-01")).sum()),
                  "zero_2026": int((zero & (X.day >= "2026-01-01")).sum()), "dayrank_col": "ph_dayrank_ph_n_makers" in Xf}), flush=True)
P = dict(TW.P0, n_jobs=int(os.environ["LGB_THREADS"]))
def fit(tr, te, cols):
    return np.array([lgb.LGBMRegressor(random_state=s, **P).fit(tr[cols], tr.logv).predict(te[cols]) for s in SEEDS]).mean(0)
months = [f"2025-{m:02d}" for m in range(3, 13)] + [f"2026-{m:02d}" for m in range(4, 11)]
rows = []
for m in months:
    te0 = X[X.mon == m]
    if not len(te0): continue
    tr0 = X[(X.mon < m) & (X.day >= "2025-01-01")]
    tr, te, cols = TW.prep(tr0, te0); base = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    trf, tef, _ = TW.prep(Xf.loc[tr0.index], Xf.loc[te0.index])
    tr, te = tr.sort_values(["day", "id"]), te.sort_values(["day", "id"]); trf, tef = trf.sort_values(["day", "id"]), tef.sort_values(["day", "id"])
    assert (te.id.values == tef.id.values).all()
    o = te[["id", "day", "dailyRank"]].copy(); o["year"] = m[:4]; o["zero_makers"] = (te0.set_index("id").ph_n_makers.reindex(te.id).values == 0)
    o["arm2"] = fit(tr, te, base); o["fix"] = fit(trf, tef, base)
    rows.append(o); print(json.dumps({"month": m, "n_test": len(te), "zero": int(o.zero_makers.sum()), "s": round(time.time() - t0)}), flush=True)
pd.concat(rows).to_parquet(OUT); print("done", flush=True)
