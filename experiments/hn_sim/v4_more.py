"""More from the same data (cached daily_v4.parquet, fully fetched days only): learning curve (30 vs all training days),
one ranker pooled over all forecast times (time as an input), and 5-seed averaging.

    python v4_more.py [split=2026-09-01] [times=t18,t21,eod]
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import daily_v4 as V
import fine_io
import top100 as H

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
TS = (sys.argv[2] if len(sys.argv) > 2 else "t18,t21,eod").split(",")
C = pd.read_parquet(os.path.join(H.CACHE, "daily_v4.parquet"))
q_all = fine_io.load()[0]
got = set(q_all.post_id[q_all.status.isin([200, 404])])
p = H.stories()
p = p[p.points >= 5]
ok = {d for d in C.day.unique() if p[(p.created_at_i >= pd.Timestamp(d, tz="UTC").timestamp() - 6 * 86400)
                                     & (p.created_at_i < pd.Timestamp(d, tz="UTC").timestamp() + 86400)].post_id.isin(got).mean() >= 0.97}
C = C[C.day.isin(ok)]
INP = list(V.VC) + ["stage1", "c_all", "c_last3h"]


def cols(t):
    return ["on_earlier_list", "text_score"] + [f"{t}_{c}" for c in INP]


def fit(df, X, seed=0):
    df = df.sort_values("day", kind="stable")
    grp = df.groupby(["day", "T"] if "T" in df else "day", sort=False).size().to_numpy()
    return lgb.LGBMRanker(n_estimators=400, learning_rate=0.05, num_leaves=15, min_child_samples=10, subsample=0.8,
                          subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=seed,
                          label_gain=list(range(31))).fit(df[X], np.clip(31 - df.real_rank, 0, 30).astype(int), group=grp)


def sc(te, s):
    return V.score(te.assign(s=np.where(te.on_earlier_list == 1, -1e9, s)), "s")["real30_in_top30"]


# pooled over times: stack rows of every T with generic column names and T as an input
pool = []
for t, off in V.TIMES.items():
    D = C[C[f"{t}_visible"] == 1][["day", "post_id", "real_rank", "on_earlier_list", "text_score"] + [f"{t}_{c}" for c in INP]]
    pool.append(D.rename(columns={f"{t}_{c}": c for c in INP}).assign(T=off))
P = pd.concat(pool, ignore_index=True)
PX = ["on_earlier_list", "text_score", "T"] + INP
mp = fit(P[P.day < SPLIT], PX)

for t in TS:
    D = C[C[f"{t}_visible"] == 1]
    tr, te = D[D.day < SPLIT], D[D.day >= SPLIT]
    last30 = sorted(tr.day.unique())[-30:]
    res = {"all train days": sc(te, fit(tr, cols(t)).predict(te[cols(t)])),
           "last 30 train days": sc(te, fit(tr[tr.day.isin(last30)], cols(t)).predict(te[cols(t)])),
           "5-seed average": sc(te, np.mean([fit(tr, cols(t), s).predict(te[cols(t)]) for s in range(5)], 0)),
           "pooled over times": sc(te, mp.predict(te.rename(columns={f"{t}_{c}": c for c in INP}).assign(T=V.TIMES[t])[PX]))}
    print(t, json.dumps({k: [round(x, 3) for x in v] for k, v in res.items()}), flush=True)
