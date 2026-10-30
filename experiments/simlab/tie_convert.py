"""Reach x conversion (Hogg & Lerman), with reach from the simulation: votes from a launch's network = tied people
(population people who backed the team before, known pre-launch) x the share of them who vote. The share is
predicted from the launch page only (ctrl.py page inputs), trained on earlier months, so the page acts through
how much of the team's network it converts. Rolling monthly (train all earlier months, test the next).
  tie_people         rank by tied people alone
  tie x page conv    log tied people + predicted log conversion
  page conv alone    predicted conversion only
Daily top 3/5 recall vs real final rank; and corr. of predicted conversion with real conversion within day.
usage: python -m simlab.tie_convert (after FROM=2026-05-01 RECIP=1 python -m simlab.tie_audit) -> reports/tie_convert.json"""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.join(os.path.dirname(HERE), "ph_predict")
sys.path.insert(0, PH)


def main():
    os.chdir(PH)
    from buildcache import build_cached
    from ctrl import group
    import model as M
    S = pd.read_parquet(f"{HERE}/cache/tie_audit_launches.parquet"); S["id"] = S.id.astype(str)
    df = build_cached(); df["id"] = df.id.astype(str)
    cols = [c for c in M.cols(df, M.LIVE_SOURCES + M.PAGE_SOURCES) if group(c) == "page"]
    A = S.merge(df[["id"] + cols], on="id")
    A["conv"] = np.log((A.tied + 0.05) / (A.tie_weighted + 0.5)); A["mon"] = A.day.str[:7]
    out = []
    for m in sorted(A.mon.unique())[1:]:
        tr, te = A[A.mon < m], A[A.mon == m].copy()
        preds = [lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1,
                                   colsample_bytree=0.5, random_state=s, verbose=-1, n_jobs=8).fit(tr[cols], tr.conv).predict(te[cols]) for s in range(3)]
        te["conv_pred"] = np.mean(preds, 0)
        off_tr, off_te = np.log(tr.tie_weighted + 0.5).values, np.log(te.tie_weighted + 0.5).values
        pp = []
        for s in range(3):   # Poisson on tied votes with reach as a fixed offset: the page explains conversion only
            b = lgb.train(dict(objective="poisson", learning_rate=0.03, num_leaves=15, min_data_in_leaf=30, bagging_fraction=0.8, bagging_freq=1,
                               feature_fraction=0.5, seed=s, verbose=-1, num_threads=8),
                          lgb.Dataset(tr[cols], tr.tied, init_score=off_tr), 400)
            pp.append(b.predict(te[cols], raw_score=True))
        te["tie x page conv (poisson)"] = off_te + np.mean(pp, 0); out.append(te)
    T = pd.concat(out)
    T["tie x page conv"] = np.log(T.tie_weighted + 0.5) + T.conv_pred
    T["page conv alone"] = T.conv_pred
    res = {"months_tested": sorted(T.mon.unique()), "days": int(T.day.nunique()), "page_inputs": len(cols)}
    for c in ("tie_people", "tie_weighted", "tie x page conv", "tie x page conv (poisson)", "page conv alone"):
        res[c] = {f"top{k}": round(100 * float(np.mean([len(set(g.nlargest(k, c).id) & set(g[g.dailyRank <= k].id)) / k
                                                       for _, g in T.groupby("day") if (g.dailyRank <= k).sum() == k])), 1) for k in (3, 5)}
    rng = np.random.default_rng(0); hit = lambda g, c, k: len(set(g.nlargest(k, c).id) & set(g[g.dailyRank <= k].id)) / k
    dd = [(hit(g, "tie x page conv (poisson)", 3) - hit(g, "tie_weighted", 3)) for _, g in T.groupby("day") if (g.dailyRank <= 3).sum() == 3]
    bs = [np.mean(rng.choice(dd, len(dd))) for _ in range(2000)]
    res["poisson_minus_reach_top3"] = {"diff": round(100 * float(np.mean(dd)), 1), "ci95": [round(100 * float(np.percentile(bs, 2.5)), 1), round(100 * float(np.percentile(bs, 97.5)), 1)],
                                       "days_better_worse": [int(sum(x > 0 for x in dd)), int(sum(x < 0 for x in dd))]}
    json.dump({i: {"tpc_poisson": float(a), "tpc_reach": float(np.log(b + 0.5))} for i, a, b in zip(T.id, T["tie x page conv (poisson)"], T.tie_weighted)},
              open(f"{PH}/data/tpc_features.json", "w"))
    per = [spearmanr(g.conv_pred, g.conv).correlation for _, g in T.groupby("day") if len(g) >= 8]
    res["conv_pred_vs_real_conv_corr"] = round(float(np.nanmean(per)), 3)
    json.dump(res, open(f"{HERE}/reports/tie_convert.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
