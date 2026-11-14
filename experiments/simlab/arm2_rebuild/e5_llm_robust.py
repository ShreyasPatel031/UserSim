"""E5 (orchestrator 12:48Z Nov 14): make arm 2 less brittle to llm_pitch noise. Arm-2 rebuild ('both' build / cols / LightGBM P0), test months
Apr-Oct 2026, 5 seeds. Variants (training AND test use the same transform):
  base   as deployed
  mono   monotone_constraints +1 on llm_pitch and llm_brand
  pct    llm_pitch -> within-day percentile rank (0..1) over the day's rows
  bin3 / bin5   llm_pitch -> 3 / 5 levels, cut points = training-row quantiles of that month
  aug2.5 / aug5   training rows' llm_pitch + N(0, sd), clipped 0..100 (once per seed); test rows untouched
Test noise: raw llm_pitch + N(0, s), s in {2.5, 5}, clipped, 3 draws, then the variant's transform. Output: id, day, dailyRank, one column per
(variant, condition)."""
import json, os, sys, time
os.environ.setdefault("LGB_THREADS", "4")
import numpy as np, pandas as pd, lightgbm as lgb
import history_retrain as HR, training_window as TW
t0 = time.time(); OUT = sys.argv[1]; rng = np.random.default_rng(0)
df, _ = HR.build(os.environ["H25_SRC"]); old = df.day < "2026-01-01"
VARS = ["base", "mono", "pct", "bin3", "bin5", "aug2.5", "aug5"]
def tf(X, v, cuts=None):
    X = X.copy()
    if v == "pct": X["llm_pitch"] = X.groupby("day").llm_pitch.rank(pct=True)
    if v in ("bin3", "bin5"): X["llm_pitch"] = np.where(X.llm_pitch.isna(), np.nan, np.searchsorted(cuts, X.llm_pitch.values, side="right"))
    return X
rows = []
for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]:
    tr, te, cols = TW.prep(df[df.mon < m], df[(df.mon == m) & ~old]); cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    o = te[["id", "day", "dailyRank"]].copy()
    noisy = {"clean": te}
    for s in (2.5, 5):
        for k in range(3):
            X = te.copy(); v = X.llm_pitch.values; X["llm_pitch"] = np.where(np.isnan(v), np.nan, np.clip(v + rng.normal(0, s, len(v)), 0, 100)); noisy[f"n{s}_d{k}"] = X
    for v in VARS:
        cuts = np.nanquantile(tr.llm_pitch, [1/3, 2/3]) if v == "bin3" else np.nanquantile(tr.llm_pitch, [.2, .4, .6, .8]) if v == "bin5" else None
        P = dict(TW.P0)
        if v == "mono": P["monotone_constraints"] = [1 if c in ("llm_pitch", "llm_brand") else 0 for c in cols]
        ms = []
        for sd in range(5):
            T = tf(tr, v, cuts)
            if v.startswith("aug"):
                a = float(v[3:]); r2 = np.random.default_rng(100 + sd); x = T.llm_pitch.values; T["llm_pitch"] = np.where(np.isnan(x), np.nan, np.clip(x + r2.normal(0, a, len(x)), 0, 100))
            ms.append(lgb.LGBMRegressor(random_state=sd, **P).fit(T[cols], T.logv))
        for cn, X in noisy.items():
            Xt = tf(X, v, cuts); o[f"{v}|{cn}"] = np.mean([mm.predict(Xt[cols]) for mm in ms], axis=0)
    rows.append(o); print(json.dumps({"month": m, "seconds": round(time.time() - t0)}), flush=True)
pd.concat(rows).to_parquet(OUT); print("done", flush=True)
