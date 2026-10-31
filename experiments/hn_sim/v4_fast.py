"""Fast model variants on the cached v4 table (daily_v4.py -> daily_v4.parquet): seconds per variant.

    python v4_fast.py [split=2026-09-01] [times=t12,t18,t21,eod]
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import top100 as H

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
TS = (sys.argv[2] if len(sys.argv) > 2 else "t12,t18,t21,eod").split(",")
C = pd.read_parquet(os.path.join(H.CACHE, "daily_v4.parquet"))
C["final_points"] = C.post_id.map(H.stories().set_index("post_id").points).fillna(1)
VC = ("points", "rank_now", "gain30", "gain60", "best_rank_D", "slots_top30_D", "slots_top10_D", "exposure_D", "age_h",
      "h_since_first_page", "assigned", "reup")


def rel(D, t):
    """Per-day relative standing at T: rank of points / exposure / gain among the day's visible candidates."""
    g = D.groupby("day")
    out = {}
    for c in ("points", "exposure_D", "gain60", "best_rank_D"):
        out[f"{t}_rk_{c}"] = g[f"{t}_{c}"].rank(ascending=c == "best_rank_D")
    return pd.DataFrame(out, index=D.index)


def ranker(tr, cols, n=400, leaves=15, obj="lambdarank"):
    tr = tr.sort_values("day", kind="stable")
    grp = tr.groupby("day", sort=False).size().to_numpy()
    lab = np.clip(31 - tr.real_rank.to_numpy(), 0, 30).astype(int)
    return lgb.LGBMRanker(objective=obj, n_estimators=n, learning_rate=0.05, num_leaves=leaves, min_child_samples=10,
                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0,
                          label_gain=list(range(31))).fit(tr[cols], lab, group=grp)


def score(P, s):
    P = P.assign(s=np.where(P.on_earlier_list == 1, -1e9, s))
    out = {}
    for k, m in ((30, 30), (10, 10)):
        v = [len(set(g[g.real_rank <= k].post_id) & set(g.nlargest(m, "s").post_id)) / k for _, g in P.groupby("day")]
        out[f"top{k}"] = R.boot(v)
    return out


for t in TS:
    D = C[C[f"{t}_visible"] == 1].copy()
    D = pd.concat([D, rel(D, t)], axis=1)
    vc = [f"{t}_{c}" for c in VC]
    cc = [f"{t}_stage1", f"{t}_c_all", f"{t}_c_last3h", "text_score", "on_earlier_list"]
    rc = [c for c in D.columns if c.startswith(f"{t}_rk_")]
    tr, te = D[D.day < SPLIT], D[D.day >= SPLIT]
    print(f"\n{t}: train {tr.day.nunique()} days, test {te.day.nunique()} days", flush=True)
    V = {
        "base (v4 + comments)": lambda: ranker(tr, vc + cc).predict(te[vc + cc]),
        "+ per-day relative ranks": lambda: ranker(tr, vc + cc + rc).predict(te[vc + cc + rc]),
        "  bigger (800 trees, 31 leaves)": lambda: ranker(tr, vc + cc + rc, 800, 31).predict(te[vc + cc + rc]),
        "  binary top-30 classifier": lambda: lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=15,
                                                                   min_child_samples=10, subsample=0.8, subsample_freq=1,
                                                                   colsample_bytree=0.8, verbose=-1, random_state=0)
        .fit(tr[vc + cc + rc], tr.real_rank <= 30).predict_proba(te[vc + cc + rc])[:, 1],
        "  final-points regressor x on-list classifier": lambda: (
            lgb.LGBMRegressor(n_estimators=400, learning_rate=0.05, num_leaves=15, verbose=-1, random_state=0)
            .fit(tr[vc + cc + rc], np.log1p(tr.final_points)).predict(te[vc + cc + rc])
            + np.log(1e-3 + lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, verbose=-1,
                                               random_state=0).fit(tr[vc + cc + rc], tr.list_rank <= 120)
                     .predict_proba(te[vc + cc + rc])[:, 1])),
    }
    for name, f in V.items():
        print(f"  {name:46s}", json.dumps(score(te, f())), flush=True)
