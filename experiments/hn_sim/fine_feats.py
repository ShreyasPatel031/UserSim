"""10-minute vote inputs for the daily-list table: reads the cached table (daily_cache.py) and the Quality News 10-minute
series (qn_fine_*.jsonl, qn.py with QN_FINE=1), adds for each forecast time T, from the 10-minute slots fully before T:
points, front-page rank, best rank so far, points gained in the last 30 / 60 min, Quality News' upvote rate (upvotes /
expected upvotes, overall and over the last hour) and the change in rank over the last hour.
-> <cache>/daily_cache_fine.parquet (fine_fetched = the story's series was fetched, or it ended under 5 points)

    python fine_feats.py
"""
import os

import numpy as np
import pandas as pd

import top100 as H

TIMES = {"t12": 12, "t15": 9, "t18": 6, "t20": 4, "t21": 3, "t22": 2, "t23": 1, "eod": 0}   # as daily_cache.py

C = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
q = pd.concat([pd.read_json(os.path.join(H.CACHE, f), lines=True) for f in sorted(os.listdir(H.CACHE))
               if f.startswith("qn_fine_") and f.endswith(".jsonl")], ignore_index=True)
p = H.stories()
fetched = set(q.post_id) | set(p.post_id[(p.points < 5).to_numpy()])
q = q[(q.status == 200) & q.qn_up_10m.map(lambda x: isinstance(x, list))].drop_duplicates("post_id")
print("series", len(q), flush=True)
RK = np.array([[x if x is not None else 91 for x in r] for r in q.qn_rank_10m], float)
UP = pd.DataFrame(list(q.qn_up_10m), dtype=float).ffill(axis=1).fillna(1).to_numpy()
EX = pd.DataFrame(list(q.qn_exp_10m), dtype=float).ffill(axis=1).fillna(0).to_numpy()
F0 = q.qn_f0.to_numpy().astype(float)
row_q = pd.Series(np.arange(len(q)), index=q.post_id).reindex(C.post_id).to_numpy()
has = ~np.isnan(row_q)
C["fine_fetched"] = C.post_id.isin(fetched).astype(np.int8)
r_ = row_q[has].astype(int)
idx = np.flatnonzero(has)
for name, off in TIMES.items():
    Tt = C.t1.to_numpy()[has] - off * 3600
    k = np.clip(((Tt - F0[r_]) // 600).astype(int), 0, 216)          # 10-minute slots fully before T
    ok = k > 0
    rr, kk, ii = r_[ok], k[ok], idx[ok]
    at = lambda M, back: M[rr, np.maximum(kk - 1 - back, 0)]
    cols = {c: np.full(len(C), np.nan) for c in ("f_points", "f_rank", "f_best_rank", "f_gain30", "f_gain60", "f_rate",
                                                  "f_rate60", "f_rank_change60")}
    cols["f_points"][ii] = at(UP, 0)
    cols["f_rank"][ii] = at(RK, 0)
    cols["f_best_rank"][ii] = np.where(np.arange(216)[None, :] < kk[:, None], RK[rr], 91).min(1)
    cols["f_gain30"][ii] = at(UP, 0) - np.where(kk > 3, at(UP, 3), 1)
    cols["f_gain60"][ii] = at(UP, 0) - np.where(kk > 6, at(UP, 6), 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        cols["f_rate"][ii] = np.where(at(EX, 0) > 0.5, at(UP, 0) / at(EX, 0), np.nan)
        d_ex = at(EX, 0) - np.where(kk > 6, at(EX, 6), 0)
        cols["f_rate60"][ii] = np.where(d_ex > 0.5, cols["f_gain60"][ii] / d_ex, np.nan)
    cols["f_rank_change60"][ii] = np.where(kk > 6, at(RK, 6), 91) - at(RK, 0)
    for c, v in cols.items():
        C[f"{name}_{c}"] = v
    print("fine inputs", name, flush=True)
out = os.path.join(H.CACHE, "daily_cache_fine.parquet")
C.to_parquet(out, index=False)
print("saved", out, C.shape, flush=True)
