"""Training emphasis for arm 2 (orchestrator 15:29Z Nov 14). Held data; counts only.
Variants (weights / targets use final ranks of TRAINING days only; unranked training rows count as the tail):
  base       arm 2 as deployed (TW.P0, unweighted log1p votes)
  band       row weight 3 for daily ranks 1-5, 2 for 6-15, 1 below
  smooth     row weight 1 / log2(1 + rank) (unranked: as rank 60)
  tail_drop  ranks > 25 (and unranked) dropped from training
  tail_w03   ranks > 25 (and unranked) weight 0.3
  wins05 / wins10   log-votes clipped from below at the training set's 5% / 10% quantile
Already closed elsewhere (not re-run): recency half-life 90/180/365 d and 2025 row weight (results/arm2_refit.md, Nov 13), LambdaRank,
classifier, reg+LambdaRank, dailyRank target, within-day rank normalisation.
Step 1 (selection, 2025 only): month-forward Mar-Dec 2025 (train on 2025 months < m), 5 seeds, top 3 on days with >= 10 ranked.
Step 2 (single test): the chosen variant vs base on 2026 Apr-Oct, arm 2 'both' training (2025 + 2026 rows, months < m), 10 seeds each,
paired day bootstrap 10,000 on the >= 10-ranked rule (183), all 214, last 90. Primary top 3, secondary top 10.
usage (VM, cwd ~/w/experiments/ph_predict): PYTHONPATH=<dir>:~/w/mk:.:~/w/h25 H25_SRC=~/w/ph_history/2025 ARM=2 python3 train_emphasis.py <out dir>"""
import json, os, sys, time
import numpy as np, pandas as pd
import lightgbm as lgb
import history_retrain as HR, training_window as TW

OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True); NJ = int(os.environ.get("LGB_THREADS", "3")); t0 = time.time()
df, _ = HR.build(os.path.expanduser(os.environ.get("H25_SRC", "~/w/ph_history/2025")))
df["id"] = df.id.astype(str); df = df.drop_duplicates("id", keep="last").reset_index(drop=True); old = (df.day < "2026-01-01").values
df["rk"] = pd.to_numeric(df.dailyRank, errors="coerce")
VARS = ["base", "band", "smooth", "tail_drop", "tail_w03", "wins05", "wins10"]


def fit_pred(tr, te, cols, var, seed):
    y = tr.logv.values.copy(); r = tr.rk.values; w = np.ones(len(tr))
    if var == "band": w = np.where(r <= 5, 3.0, np.where(r <= 15, 2.0, 1.0))
    elif var == "smooth": w = 1.0 / np.log2(1.0 + np.where(np.isfinite(r), r, 60.0))
    elif var == "tail_drop": w = np.where(np.isfinite(r) & (r <= 25), 1.0, 0.0)
    elif var == "tail_w03": w = np.where(np.isfinite(r) & (r <= 25), 1.0, 0.3)
    elif var.startswith("wins"): y = np.maximum(y, np.nanquantile(y, int(var[4:]) / 100))
    k = w > 0
    return lgb.LGBMRegressor(random_state=seed, **{**TW.P0, "n_jobs": NJ}).fit(tr[cols][k], y[k], sample_weight=w[k]).predict(te[cols])


def hits(R, col, days):
    out = []
    for d in days:
        g = R[R.day == d]; o = g.sort_values([col, "id"], ascending=[False, True]).id.tolist(); t = g.dropna(subset=["rk"]).sort_values("rk").id.tolist()
        out.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
    return np.array(out)


# step 1: selection on 2025
P = []
for m in [f"2025-{k:02d}" for k in range(3, 13)]:
    d25 = df[old]; tr0, te0 = d25[d25.mon < m], d25[d25.mon == m]
    if te0.empty: continue
    tr, te, cols = TW.prep(tr0, te0); cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    X = te[["id", "day", "rk"]].copy()
    for v in VARS: X[v] = np.mean([fit_pred(tr, te, cols, v, s) for s in range(5)], 0)
    P.append(X)
S = pd.concat(P); nr = S.groupby("day").rk.apply(lambda s: s.notna().sum()); D25 = sorted(nr[nr >= 10].index)
sel = {v: hits(S, v, D25).mean(0).round(2).tolist() for v in VARS}
best = max([v for v in VARS if v != "base"], key=lambda v: (sel[v][0], sel[v][2]))
print(json.dumps({"selection_2025_days": len(D25), "top3_5_10": sel, "chosen": best, "seconds": round(time.time() - t0)}), flush=True)
# step 2: single 2026 test, 10 seeds
P = []
for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]:
    tr0, te0 = df[df.mon < m], df[(df.mon == m) & ~old]
    tr, te, cols = TW.prep(tr0, te0); cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    X = te[["id", "day", "rk"]].copy()
    for v in ("base", best): X[v] = np.mean([fit_pred(tr, te, cols, v, s) for s in range(10)], 0)
    P.append(X); print(json.dumps({"month": m, "seconds": round(time.time() - t0)}), flush=True)
T = pd.concat(P); T.to_parquet(f"{OUT}/test_preds.parquet")
nr = T.groupby("day").rk.apply(lambda s: s.notna().sum()); D10 = sorted(nr[nr >= 10].index); rng = np.random.default_rng(0); L = []
for cut, days in (("PRIMARY >= 10 ranked", D10), ("all", sorted(T.day.unique())), ("last 90 of >= 10", D10[-90:])):
    B, C = hits(T, "base", days), hits(T, best, days); x = C - B
    bs = np.array([x[rng.integers(0, len(x), len(x))].mean(0) for _ in range(10000)])
    L.append(f"{cut} ({len(days)} d): base {B.mean(0).round(1).tolist()} {best} {C.mean(0).round(1).tolist()} diff " +
             " / ".join(f"{x[:, k].mean():+.1f} [{np.percentile(bs[:, k], 2.5):+.1f}, {np.percentile(bs[:, k], 97.5):+.1f}]" for k in range(3)))
json.dump({"selection": sel, "chosen": best, "test": L}, open(f"{OUT}/result.json", "w"), indent=1); print("\n".join(L))
