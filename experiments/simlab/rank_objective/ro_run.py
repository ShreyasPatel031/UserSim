"""Within-day ranking objectives vs regression for arm 3 (PREREG.md). Month-forward Apr-Nov 2026, 5 seeds per arm.
    cd <SP>/rb && H25_SRC=... H25_DATA=... PYTHONPATH=<SP>/rb/pp python ro_run.py <SP>"""
import json, sys, numpy as np, pandas as pd, lightgbm as lgb
import training_window as TW
SP = sys.argv[1]; SEEDS = 5; OUT = sys.argv[2] if len(sys.argv) > 2 else f"{SP}/rank_obj"
import os; os.makedirs(OUT, exist_ok=True)
X = pd.read_parquet(f"{SP}/rb/X_full.parquet"); X["id"] = X.id.astype(str); X = X.sort_values(["day", "id"]).drop_duplicates("id").reset_index(drop=True)
T = pd.read_parquet(f"{SP}/rb/arm3_feature_table.parquet"); T["id"] = T.id.astype(str); T = T.drop_duplicates("id", keep="last")
A3 = [c for c in T.columns if c.startswith("A_")] + [c for c in T.columns if c.startswith("B_")] + [c for c in T.columns if c.startswith("C_") and c.endswith("__strong")]
X = X.merge(T[["id"] + A3], on="id", how="left"); X["m"] = X.day.str[:7]

def ranks(d):
    """r = final dailyRank when present, else within-day rank by final votes (ties averaged, rounded up)."""
    vr = d.groupby("day").votes.rank(ascending=False, method="average").apply(np.ceil)
    r = pd.to_numeric(d.dailyRank, errors="coerce").fillna(vr); n = d.groupby("day").id.transform("size")
    return r, n

rows = []
for m in sorted(X.m.unique()):
    if m < "2026-04": continue
    tr, te, cols = TW.prep(X[X.m < m], X[X.m == m]); c3 = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")] + A3
    tr = tr.sort_values(["day", "id"]).reset_index(drop=True); te = te.reset_index(drop=True)
    r, n = ranks(tr); rel = np.where(r <= 10, 11 - r, 0).astype(int); pct = 1 - (r - 1) / (n - 1).clip(lower=1)
    grp = tr.groupby("day", sort=False).size().loc[tr.day.unique()].values
    P = dict(TW.P0, n_jobs=8); out = te[["id", "day", "dailyRank", "votes"]].copy()
    def avg(f): return np.mean([f(s) for s in range(SEEDS)], 0)
    out["arm3"] = avg(lambda s: lgb.LGBMRegressor(random_state=s, **P).fit(tr[c3], tr.logv).predict(te[c3]))
    for nm, obj in (("a_lambdarank", "lambdarank"), ("b_xendcg", "rank_xendcg")):
        out[nm] = avg(lambda s: lgb.LGBMRanker(random_state=s, objective=obj, label_gain=list(range(11)), **P).fit(tr[c3], rel, group=grp).predict(te[c3]))
    out["c_pctreg"] = avg(lambda s: lgb.LGBMRegressor(random_state=s, **P).fit(tr[c3], pct).predict(te[c3]))
    rows.append(out); print(m, len(tr), len(te), flush=True)
R = pd.concat(rows); R.to_parquet(f"{OUT}/preds.parquet"); print("done", len(R))
