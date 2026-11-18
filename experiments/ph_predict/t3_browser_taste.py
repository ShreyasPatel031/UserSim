"""T3 (orchestrator Nov 11): taste trained on BROWSER person-days only, choice among the full line-up (PH shows the
homepage in random order with counts hidden for ~4 h, so a browser's exposure is roughly equal across the line-up).
Browser person-day = >= 3 upvotes on the line-up that day and active >= 5 of the prior 30 days (behaviour only, T1b).
Rows: it8 base rows (rows_tl_cp_unc/X_<d>), label-filtered. Honest monthly folds: Sep browser days -> Oct test days,
Oct -> Nov. Product-only inputs (no ties, no team): within-person-day z-scores of
  base   meaning, topic, seq_last10, seq_decay, seq_nn, cat_rate_max, cat_rate_mean, cat_prior, cat_n
  +attr  it9b attr_feats columns (frozen Gemini cache)
LightGBM binary (it8 hyperparameters). Test metrics on browser person-days of Oct 20 - Nov 8: Hit@1, Hit@3,
within-line-up AUC, with random and single-feature (centroid = meaning) references; day-bootstrap CIs, paired deltas.
usage: SIMBT=<dir> python t3_browser_taste.py -> results/t3_browser_taste.json"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.special import comb
from sklearn.metrics import roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]
BASE = ["meaning", "topic", "seq_last10", "seq_decay", "seq_nn", "cat_rate_max", "cat_rate_mean", "cat_prior", "cat_n"]


def boot(x, rng, n=10000):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 2:
        return [round(float(x.mean()), 3) if len(x) else None, None, int(len(x))]
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [round(float(x.mean()), 3), [round(float(v), 3) for v in np.percentile(b, [2.5, 97.5])], int(len(x))]


def main():
    import lightgbm as lgb
    import two_level as T
    from attr_feats import AttrFeats
    ok, _ = T._label_maps(); AF = AttrFeats(WORK)
    files = {os.path.basename(f)[2:12]: f for f in glob.glob(f"{WORK}/rows_tl_cp_unc/X_*.parquet")}

    def load(d):
        X = pd.read_parquet(files[d], columns=["person", "id", "y", "w_act"] + BASE); X["id"] = X.id.astype(str)
        X = X[ok(X.person, d)].copy()
        n_up = X.groupby("person").y.transform("sum")
        X = X[(n_up >= 3) & (X.w_act * 30 >= 5)].copy()
        if not len(X):
            return X, []
        at = AF.add(X, d)
        g = X.groupby("person")
        for c in BASE + at:
            X[c] = ((X[c] - g[c].transform("mean")) / (g[c].transform("std") + 1e-9)).fillna(0)
        X["day"] = d
        return X, at
    test_days = sorted(d for d in files if "2026-10-20" <= d <= "2026-11-08")
    models, at_cols = {}, None
    for mon in sorted({d[:7] for d in test_days}):
        prev = (pd.Timestamp(mon + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m")
        tr = [load(d) for d in sorted(files) if d[:7] == prev]
        at_cols = next(a for _, a in tr if a)
        D = pd.concat([x for x, _ in tr if len(x)])
        for nm, cols in (("base", BASE), ("base+attr", BASE + at_cols)):
            models[(mon, nm)] = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1,
                                                   n_jobs=4).fit(D[cols], D.y)
        models[(mon, "_n")] = {"fit_days": len(tr), "browser_person_days": int(D.groupby(["day", "person"]).ngroups), "rows": int(len(D))}
    per = []
    for d in test_days:
        X, _ = load(d)
        if not len(X):
            continue
        X["s_base"] = models[(d[:7], "base")].predict_proba(X[BASE])[:, 1]
        X["s_attr"] = models[(d[:7], "base+attr")].predict_proba(X[BASE + at_cols])[:, 1]
        X["s_centroid"] = X.meaning; X["jit"] = np.random.default_rng(0).random(len(X)) * 1e-9
        n = X.groupby("person").size(); k = X.groupby("person").y.sum()
        row = {"day": d, "browser_person_days": int(len(n)), "random_hit1": float((k / n).mean()), "random_hit3": float((1 - comb(n - k, 3) / comb(n, 3)).mean())}
        for m in ("s_centroid", "s_base", "s_attr"):
            r = (X[m] + X.jit).groupby(X.person).rank(ascending=False, method="first")
            row[f"{m}_hit1"] = float(X[r <= 1].groupby("person").y.max().mean()); row[f"{m}_hit3"] = float(X[r <= 3].groupby("person").y.max().mean())
            au = [roc_auc_score(g.y, g[m]) for _, g in X.groupby("person") if 0 < g.y.sum() < len(g)]
            row[f"{m}_auc"] = float(np.mean(au))
        per.append(row)
    P = pd.DataFrame(per); rng = np.random.default_rng(0)
    res = {"test_days": int(len(P)), "browser_person_days": int(P.browser_person_days.sum()),
           "fits": {m: v for (m, k), v in models.items() if k == "_n"}, "attr_cols": at_cols,
           "random": {"hit1": boot(P.random_hit1, rng), "hit3": boot(P.random_hit3, rng)}}
    for m in ("s_centroid", "s_base", "s_attr"):
        res[m] = {x: boot(P[f"{m}_{x}"], rng) for x in ("hit1", "hit3", "auc")}
    res["attr_minus_base"] = {x: boot(P[f"s_attr_{x}"] - P[f"s_base_{x}"], rng) for x in ("hit1", "hit3", "auc")}
    res["base_minus_random"] = {x: boot(P[f"s_base_{x}"] - P[f"random_{x}"], rng) for x in ("hit1", "hit3")}
    json.dump(res, open(os.path.join(HERE, "results", "t3_browser_taste.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "attr_cols"}, indent=1))


if __name__ == "__main__":
    main()
