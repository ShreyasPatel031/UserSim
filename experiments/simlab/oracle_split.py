"""Where the population simulation loses launch accuracy. Per day, daily top-3/5 recall (vs real final rank) of launches
ranked by:
  sim          sum over the 30-day population of activity weight x model pick probability (what popscore does)
  who_oracle   sum of model pick probability over the pool people who really voted that day (who shows up known)
  pop_picks    real picks of the 30-day population, weighted as in sim (what they pick known, who shows up not)
  pool_votes   real votes from all pool people who voted that day (everything about the pool known)
Run with TASTE=1 to use the taste-aware person model (cache/popscore_page_taste).
usage: TASTE=1 python -m simlab.oracle_split [workers] -> reports/oracle_split.json"""
import json, os, pickle, sys
import multiprocessing as mp
import numpy as np, pandas as pd
from . import choice, popscore as PS

HERE = os.path.dirname(os.path.abspath(__file__))
DAYS_FROM, DAYS_TO = os.environ.get("FROM", "2026-08-01"), os.environ.get("TO", "2026-10-24")


def day(d):
    art = pickle.load(open(f"{PS.WORK}/model_{d[:7]}.pkl", "rb")); out = {}
    for tag, allp in (("pop", True), ("act", False)):
        D = choice.rows(day_from=d, day_to=d, all_people=allp)
        if not len(D):
            return None
        D = PS.featurize(D, art["cf"], art["prior_cut"]); D, pc = PS.page_cols(D)
        D["p"] = art["model"].predict_proba(D[PS.FEATS + pc])[:, 1]
        g = D.groupby("id")
        if allp:
            out["sim"] = (D.w * D.p).groupby(D.id).sum(); out["pop_picks"] = (D.w * D.y).groupby(D.id).sum()
        else:
            out["who_oracle"] = g.p.sum(); out["pool_votes"] = g.y.sum()
    S = pd.DataFrame(out).fillna(0).reset_index().rename(columns={"index": "id"}); S["day"] = d
    return S


def main(workers):
    PS.load()
    if PS.TASTE:
        from .page_taste import traits
        traits()
    from . import harness
    B = harness.baseline()
    days = sorted(x for x in B.day.unique() if DAYS_FROM <= x <= DAYS_TO)
    with mp.get_context("fork").Pool(workers) as pool:
        S = pd.concat([s for s in pool.map(day, days) if s is not None])
    S = S.merge(B[["id", "dailyRank"]].drop_duplicates("id"), on="id")
    res = {"days": int(S.day.nunique()), "model": PS.WORK}
    for c in ("sim", "who_oracle", "pop_picks", "pool_votes"):
        r = {}
        for k in (3, 5):
            r[f"top{k}"] = round(100 * float(np.mean([len(set(g.nlargest(k, c).id) & set(g[g.dailyRank <= k].id)) / k
                                                      for _, g in S.groupby("day") if (g.dailyRank <= k).sum() == k])), 1)
        res[c] = r
    json.dump(res, open(f"{HERE}/reports/oracle_split.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8)
