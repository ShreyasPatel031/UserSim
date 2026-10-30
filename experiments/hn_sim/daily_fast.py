"""Fast daily-list experiments on the cached table (daily_cache.py). Each variant: a stage-2 per-day ranker on chosen
columns, trained on Quality News days before SPLIT, tested from SPLIT (days whose candidates were all fetched).
Runs in seconds; edit VARIANTS and rerun.

    python daily_fast.py [split=2026-09-16]
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import top100 as H

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-16"
C = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
V = ["v_points", "v_rank_now", "v_best_rank", "v_h_top30", "v_h_top10", "v_gain3h"]
cov = C[C.day >= "2026-08-01"].groupby("day").qn_fetched.mean()
qdays = set(cov[cov >= 0.98].index)
print("days with full vote coverage:", len(qdays), min(qdays) if qdays else "", max(qdays) if qdays else "", flush=True)


def fit_rank(df, cols, leaves=15, n=300):
    df = df.sort_values("day", kind="stable")
    grp = df.groupby("day", sort=False).size().to_numpy()
    lab = np.clip(31 - df.real_rank.to_numpy(), 0, 30).astype(int)
    return lgb.LGBMRanker(n_estimators=n, learning_rate=0.05, num_leaves=leaves, min_child_samples=10, subsample=0.8,
                          subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0,
                          label_gain=list(range(31))).fit(df[cols], lab, group=grp)


def score(P, col):
    out = {}
    for k, n in ((30, 30), (10, 10), (10, 30)):
        v = [len(set(g[g.real_rank <= k].post_id) & set(g.nlargest(n, col).post_id)) / k for _, g in P.groupby("day")]
        out[f"real{k}_in_top{n}"] = R.boot(v)
    return out


for t in ("t12", "t18", "eod"):
    D = C[C.day.isin(qdays) & (C[f"{t}_visible"] == 1)].copy()
    vc = [f"{t}_{c}" for c in V]
    D[vc] = D[vc].fillna({f"{t}_v_points": 1, f"{t}_v_rank_now": 91, f"{t}_v_best_rank": 91, f"{t}_v_h_top30": 0,
                          f"{t}_v_h_top10": 0, f"{t}_v_gain3h": 0})
    trd, ted = D[D.day < SPLIT], D[D.day >= SPLIT]
    VARIANTS = {
        "stage1 (comments)": None,
        "+ votes/rank (stage 2)": [f"{t}_stage1"] + vc,
        "+ votes/rank + age, prev list": [f"{t}_stage1", f"{t}_age_h", "prev_list_rank", "posted_before_d"] + vc,
        "votes/rank only": vc + [f"{t}_age_h"],
    }
    print(f"\n{t}: train days {trd.day.nunique()}, test days {ted.day.nunique()}")
    for name, cols in VARIANTS.items():
        if cols is None:
            s = ted[f"{t}_stage1"]
        else:
            s = fit_rank(trd, cols).predict(ted[cols])
        print(f"  {name:32s}", json.dumps(score(ted.assign(s=s), "s")), flush=True)
