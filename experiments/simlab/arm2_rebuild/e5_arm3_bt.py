"""Arm 3 backtest through the production module arm3_feats.py: name normalisation plain vs strong. Seeds 5-9, month-forward Apr-Oct."""
import json, os, sys, time
os.environ.setdefault("LGB_THREADS", "4")
import numpy as np, pandas as pd, lightgbm as lgb
import history_retrain as HR, training_window as TW, arm3_feats as A3
t0 = time.time(); OUT = sys.argv[1]
df, _ = HR.build(os.environ["H25_SRC"]); old = df.day < "2026-01-01"; df = df.reset_index(drop=True)
E = np.load(os.environ["EMB"]); assert len(E) == len(df)
F = {}
for nm in ("plain", "strong"):
    X, NEW = A3.add_feats(df, E, norm=nm); F[nm] = X; print(json.dumps({"norm": nm, "C_prev 2026 test": round(float(X[(X.day >= "2026-04-01") & ~old].C_prev.mean()), 3), "s": round(time.time() - t0)}), flush=True)
rows = []
for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]:
    o = None
    for nm, X in F.items():
        tr, te, cols = TW.prep(X[X.mon < m], X[(X.mon == m) & ~old]); base = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
        if o is None:
            o = te[["id", "day", "dailyRank"]].copy(); o["base"] = np.mean([lgb.LGBMRegressor(random_state=s, **TW.P0).fit(tr[base], tr.logv).predict(te[base]) for s in range(5, 10)], axis=0)
        o[f"arm3_{nm}"] = np.mean([lgb.LGBMRegressor(random_state=s, **TW.P0).fit(tr[base + NEW], tr.logv).predict(te[base + NEW]) for s in range(5, 10)], axis=0)
    rows.append(o); print(json.dumps({"month": m, "s": round(time.time() - t0)}), flush=True)
pd.concat(rows).to_parquet(OUT); print("done", flush=True)
