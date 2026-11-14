"""PRE-REGISTERED arm 3 - arm 2 (orchestrator 20:31Z Nov 14; pending arm-3 decision). Registered before running:
  primary   top 5     secondary top 10     tertiary top 3
  2026: month-forward Apr-Oct (train on 2025 + 2026 months < m), arm-2 'both' frame (history_retrain build), 20 seeds per arm, rows sorted
        by (day, id) before every fit; arm 3 = arm-2 inputs + E5 block A (same-day line-up, bge-small) + B / C (feature table, strong names).
  2025: month-forward Mar-Dec 2025 (train on 2025 months < m only), same inputs.
  Truth: final daily rank <= k (restated rule), days with >= 10 ranked launches; paired day bootstrap 10,000 (scored separately).
Writes <out>/arm3_vs_arm2_preds.parquet (id, day, arm2, arm3) and coverage counts. Same feature code as lineup_thin_arm3.py (no thinning).
usage (VM, cwd ~/w/experiments/ph_predict): PYTHONPATH=<this dir>:~/w/mk:.:~/w/h25:<arm3 dir> H25_SRC=~/w/ph_history/2025 ARM=2
  python3 arm3_vs_arm2.py <arm3_feature_table.parquet> <arm3_emb.npz> <out dir>"""
import json, os, sys, time
import numpy as np, pandas as pd
import lightgbm as lgb
import history_retrain as HR, training_window as TW
import arm3_feats as A3

FT, EMB, OUT = sys.argv[1], sys.argv[2], sys.argv[3]; os.makedirs(OUT, exist_ok=True)
SEEDS = int(os.environ.get("SEEDS", "10")); NDRAW = int(os.environ.get("NDRAW", "20")); NJ = int(os.environ.get("LGB_THREADS", "3"))
LIVE = [0 / 12, 0 / 24, 4 / 20, 0 / 31, 3 / 30, 0 / 20, 2 / 22, 0 / 19, 1 / 18, 2 / 38, 0 / 34, 0 / 17, 2 / 25, 0 / 50, 10 / 26, 0 / 37]
WB = np.array([0.24, 0.42, 0.20, 1.05, 2.78])
t0 = time.time()
df, _ = HR.build(os.path.expanduser(os.environ.get("H25_SRC", "~/w/ph_history/2025")))
df["id"] = df.id.astype(str); df = df.drop_duplicates("id", keep="last").reset_index(drop=True); old = (df.day < "2026-01-01").values
T = pd.read_parquet(FT); T["id"] = T.id.astype(str); T = T.drop_duplicates("id", keep="last")
BC = [c for c in T.columns if c.startswith("B_")] + [c for c in T.columns if c.startswith("C_") and c.endswith("__strong")]
df = df.merge(T[["id"] + BC], on="id", how="left")
Z = np.load(EMB, allow_pickle=True); pos = {k: i for i, k in enumerate(Z["ids"])}; E = np.zeros((len(df), 384), np.float32)
have = df.id.map(pos); miss = have.isna().values
E[~miss] = Z["E"][have[~miss].astype(int).values]
if miss.any(): E[miss] = A3.embed(A3.text_of(df[miss]))
tops = [set(t) if isinstance(t, (list, tuple, np.ndarray)) else set() for t in df.topics]
hf = df.ph_hunter_followers.fillna(-1).values; hr = df.hist_hunter_rel.fillna(-9).values
DR = [c for c in df.columns if "_dayrank_" in c and c.split("_dayrank_", 1)[1] in df.columns]
print(json.dumps({"rows": len(df), "rows_2025": int(old.sum()), "embedded_now": int(miss.sum()), "bc_cols": len(BC), "dayrank_cols": len(DR),
                  "seconds": round(time.time() - t0)}), flush=True)


AC = list(A3.a_feats(np.array([0, 1]), E, [tops[0], tops[1]], hf, hr)[0].keys())

# full-list A for every row
for c in AC: df[c] = np.nan
for d, g in df.groupby("day"):
    idx = g.index.values; A = A3.a_feats(idx, E, [tops[i] for i in idx], hf, hr)
    for c in AC: df.loc[idx, c] = [A[i][c] for i in idx]

SEEDS = int(os.environ.get("SEEDS", "20"))
def fit(tr, te, cc):
    tr = tr.sort_values(["day", "id"], kind="stable"); te = te.sort_values(["day", "id"], kind="stable")
    p = np.mean([lgb.LGBMRegressor(random_state=s, **{**TW.P0, "n_jobs": NJ, "deterministic": True, "force_row_wise": True}).fit(tr[cc], tr.logv).predict(te[cc]) for s in range(SEEDS)], 0)
    return pd.Series(p, index=te.index)
P = []; COV = {}
months = [("2026", m, (df.mon < m).values, (df.mon == m).values & ~old) for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]] + \
         [("2025", m, (df.mon < m).values & old, (df.mon == m).values & old) for m in [f"2025-{k:02d}" for k in range(3, 13)]]
for yr, m, trm, tem in months:
    if tem.sum() == 0 or trm.sum() == 0: continue
    tr, te, cols = TW.prep(df[trm], df[tem]); cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month") and c not in AC + BC]
    a2 = fit(tr, te, cols); a3 = fit(tr, te, cols + AC + BC)
    COV[m] = {"test": int(len(te)), "bc_nonnull_test": round(float(te[BC].notna().any(axis=1).mean()), 3) if BC else 0.0}
    P.append(pd.DataFrame({"id": te.id.values, "day": te.day.values, "year": yr, "dailyRank": pd.to_numeric(te.dailyRank, errors="coerce").values,
                           "arm2": a2.reindex(te.index).values, "arm3": a3.reindex(te.index).values}))
    print(json.dumps({"month": m, **COV[m], "seconds": round(time.time() - t0)}), flush=True)
pd.concat(P).to_parquet(f"{OUT}/arm3_vs_arm2_preds.parquet"); json.dump(COV, open(f"{OUT}/arm3_vs_arm2_cov.json", "w"))
print(json.dumps({"done": True, "seconds": round(time.time() - t0)}))
