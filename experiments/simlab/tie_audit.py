"""How much of the population's real picks can a pre-launch person model know? Real picks of the 30-day population
(Aug 1-Oct 24) split by whether the person had a dated tie to the launch team before the day (backed: upvoted or
commented on the team's earlier launches; recip: the team engaged with the person's launches; follow is undated and reported separately). Daily top-3/5 recall of launches ranked by:
  all real picks, tied picks only, untied picks only, and the taste model's predicted picks.
usage: RECIP=1 python -m simlab.tie_audit [workers] -> reports/tie_audit.json"""
import json, os, sys
import multiprocessing as mp
import numpy as np, pandas as pd
from . import choice, popscore as PS

HERE = os.path.dirname(os.path.abspath(__file__))


def day(d):
    cf = G[d[:7]]
    D = choice.rows(day_from=d, day_to=d, all_people=True)
    if not len(D):
        return None
    D = PS.featurize(D, cf, PS.month_start(d[:7], 1))
    tie = (D.backed.values > 0) | (D.recip_team.values > 0)   # dated ties only (backed is a log count, not ranked)
    D["tie"] = tie; D["fol"] = D.follow > 0
    D["wy"] = D.w * D.y
    out = D.groupby("id").agg(all=("wy", "sum")).join(D[D.tie].groupby("id").wy.sum().rename("tied")) \
           .join(D[~D.tie].groupby("id").wy.sum().rename("untied")).join(D[D.tie | D.fol].groupby("id").wy.sum().rename("tied_or_follow")).fillna(0)
    out["day"] = d
    st = {"picks": float(D.wy.sum()), "tied": float(D.wy[D.tie].sum()), "follow": float(D.wy[D.fol].sum()), "tied_or_follow": float(D.wy[D.tie | D.fol].sum())}
    return out.reset_index(), st


G = {}


def main(workers):
    PS.load()
    from . import harness
    B = harness.baseline()
    days = sorted(x for x in B.day.unique() if "2026-08-01" <= x <= "2026-10-24")
    for m in sorted({d[:7] for d in days}):
        G[m] = PS.fit_cf(PS.month_start(m, 1))
    with mp.get_context("fork").Pool(workers) as pool:
        R = [r for r in pool.map(day, days) if r is not None]
    S = pd.concat([r[0] for r in R]).merge(B[["id", "dailyRank"]].drop_duplicates("id"), on="id")
    tot = pd.DataFrame([r[1] for r in R]).sum()
    res = {"days": len(R), "share_of_picks_tied": round(float(tot.tied / tot.picks), 3), "share_follow": round(float(tot.follow / tot.picks), 3),
           "share_tied_or_follow": round(float(tot.tied_or_follow / tot.picks), 3)}
    for c in ("all", "tied", "untied", "tied_or_follow"):
        res[c] = {f"top{k}": round(100 * float(np.mean([len(set(g.nlargest(k, c).id) & set(g[g.dailyRank <= k].id)) / k
                                                       for _, g in S.groupby("day") if (g.dailyRank <= k).sum() == k])), 1) for k in (3, 5)}
    json.dump(res, open(f"{HERE}/reports/tie_audit.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 16)
