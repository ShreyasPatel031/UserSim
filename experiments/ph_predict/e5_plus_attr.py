"""it9b attributes on top of E5's product-only taste (orchestrator / E5 Nov 11), 12 clean days.
E5 rows: tmp/e5/e5_ref_rows_12clean.parquet (d, person_id, launch_id, y, product_only, full; label-filtered, E5's model).
Features per row: E5's product_only score + it9b attr_feats columns (frozen Gemini cache; person prefs from launches
dated <= d-2), z-scored within person-day. Combiner = LightGBM binary (small: 200 trees, 15 leaves), fitted
  (i) leave-one-day-out over the 12 days, (ii) forward-only (each test day fitted on earlier days only; first 3 days
  have no fit and are skipped).
Metrics on voting person-days (>= 1 positive): Hit@1, Hit@3, within-line-up AUC, against E5 product_only alone,
paired by day (bootstrap).
usage: SIMBT=<dir> python e5_plus_attr.py -> results/e5_plus_attr.json"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"


def boot(x, rng, n=10000):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 2:
        return [round(float(x.mean()), 3) if len(x) else None, None, int(len(x))]
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [round(float(x.mean()), 3), [round(float(v), 3) for v in np.percentile(b, [2.5, 97.5])], int(len(x))]


def metrics(X, col):
    S = X[X.groupby("person").y.transform("sum") > 0]
    r = (S[col] + S.jit).groupby(S.person).rank(ascending=False, method="first")
    au = [roc_auc_score(g.y, g[col]) for _, g in S.groupby("person") if 0 < g.y.sum() < len(g)]
    return {"hit1": float(S[r <= 1].groupby("person").y.max().mean()), "hit3": float(S[r <= 3].groupby("person").y.max().mean()),
            "auc": float(np.mean(au)) if au else np.nan}


def main():
    import lightgbm as lgb
    from attr_feats import AttrFeats
    tmp = tempfile.mkdtemp(); subprocess.run(["gsutil", "-q", "cp", f"{B}/tmp/e5/e5_ref_rows_12clean.parquet", tmp], check=True)
    E = pd.read_parquet(f"{tmp}/e5_ref_rows_12clean.parquet").rename(columns={"person_id": "person", "launch_id": "id"})
    E["id"] = E.id.astype(str); E["d"] = E.d.astype(str)
    AF = AttrFeats(WORK); days = sorted(E.d.unique()); parts = {}
    for d in days:
        X = E[E.d == d].copy(); at = AF.add(X, d)
        g = X.groupby("person")
        for c in ["product_only"] + at:
            X[c + "_z"] = ((X[c] - g[c].transform("mean")) / (g[c].transform("std") + 1e-9)).fillna(0)
        X["jit"] = np.random.default_rng(0).random(len(X)) * 1e-9
        parts[d] = X
    cols = ["product_only_z"] + [c + "_z" for c in at]
    rng = np.random.default_rng(0); res = {"days": days, "rows": int(len(E)), "features": cols}
    for scheme in ("lodo", "forward"):
        per = []
        for d in days:
            tr = [x for x in days if (x != d if scheme == "lodo" else x < d)]
            if len(tr) < 3:
                continue
            T = pd.concat([parts[x] for x in tr])
            if os.environ.get("VOTERS_ONLY", "1") == "1":   # second run: fit on voting person-days only (choice, not activity)
                T = T[T.groupby(["d", "person"]).y.transform("sum") > 0]
            m = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=100, verbose=-1, n_jobs=4).fit(T[cols], T.y)
            X = parts[d].copy(); X["comb"] = m.predict_proba(X[cols])[:, 1]
            a, b = metrics(X, "product_only"), metrics(X, "comb")
            per.append({"day": d, **{f"e5_{k}": v for k, v in a.items()}, **{f"comb_{k}": v for k, v in b.items()}})
        P = pd.DataFrame(per)
        res[scheme] = {"days": int(len(P)), **{f"{m}_{k}": boot(P[f"{m}_{k}"], rng) for m in ("e5", "comb") for k in ("hit1", "hit3", "auc")},
                       **{f"delta_{k}": boot(P[f"comb_{k}"] - P[f"e5_{k}"], rng) for k in ("hit1", "hit3", "auc")}}
    json.dump(res, open(os.path.join(HERE, "results", "e5_plus_attr.json"), "w"), indent=1)
    for sc in ("lodo", "forward"):
        print(sc, json.dumps({k: (v[:2] if isinstance(v, list) else v) for k, v in res[sc].items()}))


if __name__ == "__main__":
    main()
