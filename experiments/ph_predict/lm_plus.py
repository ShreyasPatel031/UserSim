"""Launch model + extra pre-launch inputs, daily top 3/5/10, paired by day.
Variants (LightGBM on final log votes, rolling monthly: train on earlier months, 3 seeds):
  refit alone       the launch model's prediction (ctrl.py `all`) as the only input: the control, since every variant
                    below refits on that prediction and a refit alone can move the score
  + competitors     + competitor grounding (data/<CMP>.json, cmp_ inputs; NaN where the launch has no safe list)
  + <sim>           + the person simulation's inputs (data/<sim>_features.json, log1p, plus within-day percentiles)
  + both
The raw launch model (no refit) is reported too. Deltas: each variant vs refit alone and vs the raw launch model.
Launches: those the simulation file covers (competitor inputs left-joined).
usage: SIMLAB_DATA=data_v2 python lm_plus.py pna cmp_features_ph -> results/lm_plus_<sim>_<cmp>.json"""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store


def topk(T, col, k):
    return pd.Series({d: len(set(g.nlargest(k, col).id) & set(g[g.out_dailyRank <= k].id)) / k for d, g in T.groupby("day") if (g.out_dailyRank <= k).sum() == k})


def boot(a, b, rng):
    ks = a.index.intersection(b.index); d = (b[ks] - a[ks]).values
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
    return [round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])], int(len(d))]


def main(sim, cmp):
    P, I, E = store.load(); I = I.assign(id=I.id.astype(str))
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
    S = pd.DataFrame.from_dict(json.load(open(f"data/{sim}_features.json")), orient="index").rename_axis("id").reset_index()
    K = pd.DataFrame.from_dict(json.load(open(f"data/{cmp}.json")), orient="index").rename_axis("id").reset_index()
    A = C[["id", "day", "logv", "all"]].merge(I[["id", "out_dailyRank"]], on="id").merge(S, on="id").merge(K, on="id", how="left")
    sc = [c for c in S if c != "id"]; kc = [c for c in K if c.startswith("cmp_")]
    for c in sc:
        if not c.endswith(("pmax", "share")):
            A[c] = np.log1p(A[c].clip(lower=0))
        A[c + "_dayr"] = A.groupby("day")[c].rank(pct=True)
    sc = sc + [c + "_dayr" for c in sc]
    A["mon"] = A.day.str[:7]
    V = {"refit alone": ["all"], "+ competitors": ["all"] + kc, f"+ {sim}": ["all"] + sc, "+ both": ["all"] + kc + sc}
    out = []
    for m in sorted(A.mon.unique())[1:]:
        tr, te = A[A.mon < m], A[A.mon == m].copy()
        for name, cols in V.items():
            te[name] = np.mean([lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1,
                                                  colsample_bytree=0.5, random_state=r, verbose=-1, n_jobs=8).fit(tr[cols], tr.logv).predict(te[cols]) for r in range(3)], 0)
        out.append(te)
    T = pd.concat(out); rng = np.random.default_rng(0)
    res = {"launches": len(T), "days": int(T.day.nunique()), "months_tested": sorted(T.mon.unique()),
           "competitor_coverage": round(float(T[kc[0]].notna().mean()), 3) if kc else 0}
    for k in (3, 5, 10):
        raw, ref = topk(T, "all", k), topk(T, "refit alone", k)
        line = {"launch model (raw)": round(100 * float(raw.mean()), 1), "refit alone": round(100 * float(ref.mean()), 1)}
        for name in list(V)[1:]:
            cur = topk(T, name, k)
            line[name] = {"score": round(100 * float(cur.mean()), 1), "vs refit alone": boot(ref, cur, rng), "vs raw launch model": boot(raw, cur, rng)}
        res[f"daily top{k}"] = line
    json.dump(res, open(f"results/lm_plus_{sim}_{cmp}.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
