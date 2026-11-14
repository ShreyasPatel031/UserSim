"""E5 (orchestrator 12:36Z Nov 14): what could averaging llm_pitch / llm_brand samples buy? Arm-2 rebuild ('both', same build / cols /
fit as e5_a2_labels.py base). Trained models are fixed; at inference the TEST rows' llm_pitch (and/or llm_brand) get added Gaussian
noise of sd s (clipped to the score range), 3 noise draws per s, and the predictions are averaged over 5 seeds per draw.
Also 'blank' = both scores missing at inference. Output parquet: id, day, dailyRank, one column per condition (mean over draws of
each draw's ranking is not meaningful, so each draw is a separate column; scoring averages the per-draw top-k)."""
import json, os, sys, time
os.environ.setdefault("LGB_THREADS", "4")
import numpy as np, pandas as pd, lightgbm as lgb
import history_retrain as HR, training_window as TW
t0 = time.time(); OUT = sys.argv[1]; rng = np.random.default_rng(0)
df, _ = HR.build(os.environ["H25_SRC"]); old = df.day < "2026-01-01"
CONDS = [("pitch", s) for s in (2.5, 5, 10, 15)] + [("brand", s) for s in (0.15, 0.35, 0.7)] + [("both", None)]
rows = []
for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]:
    tr, te, cols = TW.prep(df[df.mon < m], df[(df.mon == m) & ~old]); cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    ms = [lgb.LGBMRegressor(random_state=s, **TW.P0).fit(tr[cols], tr.logv) for s in range(5)]
    pr = lambda X: np.mean([mm.predict(X[cols]) for mm in ms], axis=0)
    o = te[["id", "day", "dailyRank"]].copy(); o["base"] = pr(te)
    for what, s in CONDS:
        if s is None:
            X = te.copy(); X[["llm_pitch", "llm_brand"]] = np.nan; o["blank"] = pr(X); continue
        col, hi = ("llm_pitch", 100) if what == "pitch" else ("llm_brand", 3)
        for k in range(3):
            X = te.copy(); v = X[col].values; X[col] = np.where(np.isnan(v), np.nan, np.clip(v + rng.normal(0, s, len(v)), 0, hi))
            o[f"{what}_{s}_d{k}"] = pr(X)
    rows.append(o); print(json.dumps({"month": m, "seconds": round(time.time() - t0)}), flush=True)
pd.concat(rows).to_parquet(OUT); print("done", flush=True)
