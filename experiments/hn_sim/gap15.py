"""Why is Caught at 15 min 24.7% over Sep 1 - Oct 14 but 29.6% on Oct 2-14 (wb15)? And one fix.

Headline model (caught.py): train posts Jul-Aug, test Sep 1 - Oct 14, inputs = at-posting + front-page rank by 15 min
(Quality News, rank only). wb15's 29.6% adds comments and who commented by 15 min, the history score, the page judge,
Wayback /newest votes and exposure (dense only Oct 2-16), and retrains daily.
1. Split the headline by period (Sep 1-30, Oct 1-14) and by winner type (flags = winners over the whole test period).
2. Fix: give the full-period model every 15-min input that exists for the whole period (comments + who by 15 min,
   history score, page judge; Wayback votes / exposure where a capture exists, missing otherwise - capture timing does
   not depend on the outcome). Same train / test, paired vs the headline; split by period again.

    python gap15.py
"""
import os

import numpy as np
import pandas as pd

import caught as C
import caught1h as C1
import fine_io
import odds_live as OL
import pj_eval
import top100 as H
import wb15 as W15


def split(name, s, Q, kind):
    T = Q[C.te][["day", "y"]].assign(s=s, kind=kind[C.te])
    k = int(T.y.sum())
    T["flag"] = T.s.rank(ascending=False, method="first") <= k
    parts = []
    for lab, m in (("Sep 1-30", T.day < "2026-10-01"), ("Oct 1-14", T.day >= "2026-10-01")):
        g = T[m]
        parts.append(f"{lab} {int((g.flag & (g.y == 1)).sum())}/{int(g.y.sum())} = {(g.flag & (g.y == 1)).sum() / max(g.y.sum(), 1):.1%} "
                     f"(flags used {int(g.flag.sum())})")
    types = ", ".join(f"{t} {int((T.flag & (T.kind == t)).sum())}/{int((T.kind == t).sum())}" for t in ("fast", "late", "reup"))
    print(f"   {name}: " + "; ".join(parts) + f"; by type: {types}", flush=True)


def main():
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    C.Q = Q
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [15])[15], 15, set(qb))[["rank_now", "best_rank"]]
    vis60 = (OL.vote_feats(Q, qb, [60])[60].best_rank <= 30).to_numpy()
    L = OL.lists()
    first = L[L["rank"] <= 30].groupby("post_id").day.min()
    lag = (pd.to_datetime(Q.post_id.map(first)) - pd.to_datetime(Q.day)).dt.days.to_numpy()
    y = Q.y.to_numpy()
    kind = np.where(y == 0, "none", np.where(lag >= 2, "reup", np.where(vis60, "fast", "late")))
    full = C.POST + C.KNN + C.EMB + C.CROWD
    s0 = C.model(full, R)
    a0 = C.caught(s0)
    print(f"headline 15-min model (at posting + front rank): {C.ci(a0)}", flush=True)
    split("headline", s0, Q, kind)
    C1.Q = Q
    CM, WHO = C1.comments(15)
    V, XP = W15.votes15(Q), W15.expo15(Q)
    print(f"Wayback /newest snapshot by 15 min: Sep {V.v_has[C.te & (Q.day < '2026-10-01').to_numpy()].mean():.1%} of posts, "
          f"Oct 1-14 {V.v_has[C.te & (Q.day >= '2026-10-01').to_numpy()].mean():.1%}", flush=True)
    PJ = [c for c in Q.columns if c.startswith("pj_")]
    steps = [("+ comments + who by 15 min", pd.concat([R, CM[["cm_n", "cm_people", "cm_first"]], WHO], axis=1), []),
             ("+ history score + page judge", pd.concat([R, CM[["cm_n", "cm_people", "cm_first"]], WHO], axis=1), ["hist_prior"] + PJ),
             ("+ Wayback votes + exposure (where captured)", pd.concat([R, CM[["cm_n", "cm_people", "cm_first"]], WHO, V, XP], axis=1),
              ["hist_prior"] + PJ)]
    for name, extra, cols in steps:
        s = C.model(full + cols, extra)
        a = C.caught(s)
        print(f"{name}: {C.ci(a)}  vs headline {C.diff(a, a0)}", flush=True)
        split(name, s, Q, kind)


if __name__ == "__main__":
    main()
