"""Daily list v4: built on how HN files stories. Every story is on exactly one day's list (checked on 20,159 stories);
that day is the UTC day of its displayed time, which HN resets when it re-ups a story from the second-chance pool. So:
assignment time ~ first front-page appearance if it came more than 30 min after posting, else posting time (93.6% of
list entries land on the right day). Second-chance stories come back days later, so candidates reach back 7 days.

For a forecast at T on day D, per candidate (only what is known at T, from Quality News' 10-minute series kept for the
story's whole life): points, rank, best rank and time in the top 30 / top 10 during D so far, exposure during D, points
gained in the last 30 / 60 min, hours since posting and since first reaching the front page, whether its assignment
day is already D / earlier / still open, whether it is on an earlier day's list (then it cannot be on D), plus the
comment-based stage-1 score from daily_cache.parquet (stories under 72 h).
Old stories (over 72 h at the end of D) are candidates at T only once they have been on the front page during D by T.

Stage 2: per-T LambdaRank on days before SPLIT, tested from SPLIT.

    python daily_v4.py [split=2026-09-01] [from=2026-07-06] [to=2026-10-16]
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import fine_io
import rank as R
import top100 as H

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
A = sys.argv[2] if len(sys.argv) > 2 else "2026-07-06"
B = sys.argv[3] if len(sys.argv) > 3 else "2026-10-16"
TIMES = {"t12": 12, "t15": 9, "t18": 6, "t20": 4, "t21": 3, "t22": 2, "t23": 1, "eod": 0}
NS = 1008                                                      # 10-minute slots: 7 days

L = pd.read_json(os.path.join(H.CACHE, "frontday.jsonl"), lines=True, dtype={"day": str})
L = L.sort_values("rank").drop_duplicates(["day", "post_id"])
p = H.stories()
pts = p.set_index("post_id").points
q_all, q = fine_io.load()
fetched = set(q_all.post_id)
print("series", len(q), flush=True)

# full 7-day series per story: rank (91 = not on the front page) and upvotes (carried forward)
n = len(q)
RK = np.full((n, NS), 91, np.float32)
UP = np.full((n, NS), np.nan, np.float32)
RK[:, :216] = np.array([[x if x is not None else 91 for x in r] for r in q.qn_rank_10m], np.float32)
UP[:, :216] = pd.DataFrame(list(q.qn_up_10m), dtype=float).to_numpy()
for r, late in enumerate(q.qn_late if "qn_late" in q else [None] * n):
    if isinstance(late, list):
        for k, rk, up, _ in late:
            RK[r, k], UP[r, k] = rk, up
UP = pd.DataFrame(UP).ffill(axis=1).fillna(1).to_numpy(np.float32)
F0 = q.qn_f0.to_numpy().astype(float)
born = q.post_id.map(p.set_index("post_id").created_at_i).to_numpy().astype(float)
on = RK <= 90
k_first = np.where(on.any(1), on.argmax(1), -1)
t_first = np.where(k_first >= 0, F0 + 600 * (k_first + 1), np.nan)   # end of the first on-page slot
reup = (t_first - born) > 1800
t_assign = np.where(reup, t_first, born)                             # known once the story reached the page
qi = pd.Series(np.arange(n), index=q.post_id)

# earlier lists: a story on any earlier day's list (any rank) cannot be on D
first_list_day = L.groupby("post_id").day.min()

S1 = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"),
                     columns=["day", "post_id", "text_score"] + [f"{t}_{c}" for t in TIMES for c in ("stage1", "c_all", "c_last3h")])

rows = []
days = sorted(d for d in L.day.unique() if A <= d <= B)
for d in days:
    t0 = pd.Timestamp(d, tz="UTC").timestamp()
    t1 = t0 + 86400
    young = (born >= t1 - 72 * 3600) & (born < t1)
    k0 = np.floor((t0 - F0) / 600).astype(int)
    k1 = np.floor((t1 - F0) / 600).astype(int)
    old = (born >= t1 - 7 * 86400) & (born < t1 - 72 * 3600) & (k1 > 0) & (k0 < NS)
    old &= np.array([on[r, max(k0[r], 0):min(k1[r], NS)].any() if o else False for r, o in enumerate(old)])
    c = np.flatnonzero(young | old)
    rows.append(pd.DataFrame({"day": d, "r": c, "t0": t0, "t1": t1}))
C = pd.concat(rows, ignore_index=True)
C["post_id"] = q.post_id.to_numpy()[C.r]
lr = L.set_index(["day", "post_id"])["rank"]
C["list_rank"] = lr.reindex(pd.MultiIndex.from_frame(C[["day", "post_id"]])).fillna(999).to_numpy()
C["real_rank"] = np.where(C.list_rank <= 30, C.list_rank, 999)
C["on_earlier_list"] = (C.post_id.map(first_list_day).fillna("9999") < C.day).astype(np.int8)
C = C.merge(S1, on=["day", "post_id"], how="left")
print("rows", len(C), "days", C.day.nunique(), flush=True)

r = C.r.to_numpy()
WIN = 144 + 1                                                   # slots in one day (+1 edge)
feats = {}
for name, off in TIMES.items():
    T = C.t1.to_numpy() - off * 3600
    kT = np.clip(np.floor((T - F0[r]) / 600).astype(int), 0, NS)           # slots fully before T
    kD = np.clip(np.floor((C.t0.to_numpy() - F0[r]) / 600).astype(int), 0, NS)
    last = np.maximum(kT - 1, 0)
    idx = kD[:, None] + np.arange(WIN)[None, :]
    inwin = idx < kT[:, None]
    idxc = np.minimum(idx, NS - 1)
    rkD = np.where(inwin, RK[r[:, None], idxc], 91)
    f = {}
    f["points"] = np.where(kT > 0, UP[r, last], 1)
    f["rank_now"] = np.where(kT > 0, RK[r, last], 91)
    f["gain30"] = f["points"] - np.where(kT > 3, UP[r, np.maximum(kT - 4, 0)], 1)
    f["gain60"] = f["points"] - np.where(kT > 6, UP[r, np.maximum(kT - 7, 0)], 1)
    f["best_rank_D"] = rkD.min(1)
    f["slots_top30_D"] = (rkD <= 30).sum(1)
    f["slots_top10_D"] = (rkD <= 10).sum(1)
    f["exposure_D"] = np.where(rkD < 91, 1 / rkD, 0).sum(1)
    f["age_h"] = (T - born[r]) / 3600
    seen = t_first[r] <= T
    f["h_since_first_page"] = np.where(seen, (T - t_first[r]) / 3600, -1)
    # assignment day so far: 1 = D, -1 = earlier day, 0 = not yet on the page (still open)
    f["assigned"] = np.where(~seen, 0, np.where(t_assign[r] >= C.t0.to_numpy(), 1, -1))
    f["reup"] = np.where(seen, reup[r].astype(float), 0)
    f["visible"] = ((born[r] < T) & ((C.t1.to_numpy() - born[r] <= 72 * 3600) | (f["slots_top30_D"] + (rkD < 91).sum(1) > 0))).astype(np.int8)
    for k_, v in f.items():
        C[f"{name}_{k_}"] = v
    print("inputs", name, flush=True)
C.drop(columns=["r"]).to_parquet(os.path.join(H.CACHE, "daily_v4.parquet"), index=False)


def fit_rank(df, cols):
    df = df.sort_values("day", kind="stable")
    grp = df.groupby("day", sort=False).size().to_numpy()
    lab = np.clip(31 - df.real_rank.to_numpy(), 0, 30).astype(int)
    return lgb.LGBMRanker(n_estimators=400, learning_rate=0.05, num_leaves=15, min_child_samples=10, subsample=0.8,
                          subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0,
                          label_gain=list(range(31))).fit(df[cols], lab, group=grp)


def score(P, col):
    out = {}
    for k, m in ((30, 30), (10, 10), (10, 30)):
        v = [len(set(g[g.real_rank <= k].post_id) & set(g.nlargest(m, col).post_id)) / k for _, g in P.groupby("day")]
        out[f"real{k}_in_top{m}"] = R.boot(v)
    return out


base = ["on_earlier_list", "text_score"]
for t in TIMES:
    vc = [f"{t}_{c}" for c in ("points", "rank_now", "gain30", "gain60", "best_rank_D", "slots_top30_D", "slots_top10_D",
                                "exposure_D", "age_h", "h_since_first_page", "assigned", "reup")]
    cc = [f"{t}_stage1", f"{t}_c_all", f"{t}_c_last3h"]
    D = C[C[f"{t}_visible"] == 1]
    trd, ted = D[D.day < SPLIT], D[D.day >= SPLIT]
    print(f"\n{t}: train days {trd.day.nunique()}, test days {ted.day.nunique()}, real top 30 visible "
          f"{(ted.real_rank <= 30).sum() / ted.day.nunique() / 30:.3f}", flush=True)
    for vname, cols in (("v4 votes/page only", base + vc), ("v4 + comments stage 1", base + vc + cc)):
        s = fit_rank(trd, cols).predict(ted[cols])
        s = np.where(ted.on_earlier_list == 1, -1e9, s)
        print(f"  {vname:28s}", json.dumps(score(ted.assign(s=s), "s")), flush=True)
