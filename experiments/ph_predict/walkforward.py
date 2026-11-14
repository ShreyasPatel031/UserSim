"""Walk-forward backtest mirroring the live retrain (orchestrator 15:45Z Nov 14). Counts only.
Live: forecast.py retrains every night on all labelled day files present at 00:05, i.e. days <= d-2 (the ranks step writes d-1 after the
forecast), arm 2 via h25_live (2025 + 2026 rows, old-row NaN rules) and clean_nosite on the plain 2026 build.
Here: for each test day d (Apr-Oct 2026) the model is trained on days <= d-2 with a refit every STEP days (STEP=1 = nightly, as live;
STEP=7 = weekly: the refit on day r serves days r .. r+6, each still trained only on days <= r-2, so it is staler than live, never leakier).
Same feature build and prep as the month-forward backtest (history_retrain DECOMP: 'both' = arm 2, 'pure' = clean_nosite-style plain 2026),
TW.prep, TW.P0, 5 seeds. Writes <out>/wf_preds.parquet (id, day, both, pure).
usage (VM, cwd ~/w/experiments/ph_predict): PYTHONPATH=<dir>:~/w/mk:.:~/w/h25 H25_SRC=~/w/ph_history/2025 ARM=2 STEP=7 python3 walkforward.py <out>"""
import json, os, sys, time
import numpy as np, pandas as pd
import lightgbm as lgb
import features as F, run as RN, history_retrain as HR, training_window as TW

OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True); STEP = int(os.environ.get("STEP", "7")); SEEDS = int(os.environ.get("SEEDS", "5"))
NJ = int(os.environ.get("LGB_THREADS", "4")); t0 = time.time()
df, _ = HR.build(os.path.expanduser(os.environ.get("H25_SRC", "~/w/ph_history/2025"))); old = df.day < "2026-01-01"
real = os.path.join(os.path.dirname(os.path.abspath(F.__file__)), "data"); Fh = F.D; F.D = real; dfo = RN.load_llm(F.build()); F.D = Fh
dfo = dfo[~dfo.known].copy(); dfo["id"] = dfo.id.astype(str); dfo["mon"] = dfo.day.str[:7]; df["id"] = df.id.astype(str)
days = sorted(d for d in dfo.day.unique() if "2026-04-01" <= d <= "2026-10-31")
refits = days[::STEP]; P = []
for i, r in enumerate(refits):
    serve = [d for d in days if r <= d < (refits[i + 1] if i + 1 < len(refits) else "9999")]
    cut = (pd.Timestamp(r) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    for nm, D, tem in (("both", df, ~old), ("pure", dfo, pd.Series(True, index=dfo.index))):
        tr0 = D[D.day <= cut]; te0 = D[D.day.isin(serve) & tem]
        if te0.empty: continue
        tr, te, cols = TW.prep(tr0, te0); cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
        p = np.mean([lgb.LGBMRegressor(random_state=s, **{**TW.P0, "n_jobs": NJ}).fit(tr[cols], tr.logv).predict(te[cols]) for s in range(SEEDS)], 0)
        P.append(pd.DataFrame({"id": te.id.values, "day": te.day.values, "variant": nm, "pred": p, "refit": r, "cut": cut}))
    if i % 5 == 0: print(json.dumps({"refit": r, "of": len(refits), "seconds": round(time.time() - t0)}), flush=True)
R = pd.concat(P); W_ = R.pivot_table(index=["id", "day"], columns="variant", values="pred").reset_index()
W_ = W_.merge(R[R.variant == "both"][["id", "refit"]], on="id", how="left"); W_.to_parquet(f"{OUT}/wf_preds_step{STEP}.parquet")
print(json.dumps({"rows": len(W_), "days": W_.day.nunique(), "step": STEP, "seconds": round(time.time() - t0)}))
