"""Does Gemini's page reading (ps_*) predict the launch? On the launches that have page scores:
  1. each element alone: rank correlation with the real daily rank, within day
  2. the live model with vs without ps_*, rolling monthly, 5 seeds (scored only on days with page scores)
  3. each element's weight: share of the model's split gain, and the loss when only that element is removed
usage: python psexp.py -> results/psexp.json"""
import json, multiprocessing as mp, os
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr
import model as M, run as RN
from buildcache import build_cached

LIVE = M.LIVE_SOURCES
P = dict(colsample_bytree=0.5)
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]


def job(a):
    m, tr, te, seed, drop = a
    tr, te = M.add_fold_feats(tr, te)
    out = {"id": te.id.values, "seed": seed}
    out["live"] = M.fit_predict(tr, te, LIVE, seed=seed, **P)[0]
    pred, mdl, cols = M.fit_predict(tr, te, LIVE + ["ps"], seed=seed, **P)
    out["live+ps"] = pred
    gain = dict(zip(cols, mdl.booster_.feature_importance("gain"))) if mdl is not None else {}
    for c in drop:
        out[f"-{c}"] = M.fit_predict(tr.drop(columns=[c]), te.drop(columns=[c]), LIVE + ["ps"], seed=seed, **P)[0]
    return pd.DataFrame(out), gain


def main():
    df = build_cached(); df = df[~df.known].copy()
    ps = [c for c in df.columns if c.startswith("ps_")]
    has = df[ps].notna().any(axis=1)
    days = set(df[has].day)
    res = {"launches_with_scores": int(has.sum()), "days": len(days)}
    S = df[has & df.dailyRank.notna()]
    res["alone_rank_corr"] = {c: round(float(np.nanmean([spearmanr(g[c], -g.dailyRank).correlation for _, g in S.groupby("day")
                                                         if g[c].nunique() > 1])), 3) for c in ps}
    folds = [(m, tr, te) for m, tr, te in RN.folds(df, MONTHS) if te.day.isin(days).any()]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        out = pool.map(job, [(m, tr, te, s, ps) for m, tr, te in folds for s in range(5)])
    Pd = pd.concat([o[0] for o in out]); gain = pd.DataFrame([o[1] for o in out]).mean()
    V = [c for c in Pd.columns if c not in ("id", "seed")]
    A = Pd.groupby("id")[V].mean().reset_index().merge(df[["id", "day", "dailyRank"]], on="id")
    A = A[A.day.isin(days) & A.dailyRank.notna()]
    sc = {v: [round(100 * np.mean(M.recall_at(A, "day", "dailyRank", k, v, per_list=True)), 1) for k in (3, 5, 10)] for v in V}
    res["top3_5_10"] = {"live": sc["live"], "live+ps": sc["live+ps"]}
    tot = gain.sum()
    res["elements"] = {c: {"gain_share_pct": round(100 * gain.get(c, 0) / tot, 2), "loss_if_removed_top3_5_10":
                           [round(a - b, 1) for a, b in zip(sc["live+ps"], sc[f"-{c}"])]} for c in ps}
    json.dump(res, open("results/psexp.json", "w"), indent=1)
    print(json.dumps({k: res[k] for k in ("launches_with_scores", "days", "top3_5_10")}, indent=1))
    print(pd.DataFrame(res["elements"]).T.sort_values("gain_share_pct", ascending=False).to_string())
    print(pd.Series(res["alone_rank_corr"]).sort_values(ascending=False).to_string())


if __name__ == "__main__":
    main()
