"""Build once, iterate fast: one cached table of daily-list candidate rows with every input at each forecast time,
plus stage-1 scores, so model experiments (daily_fast.py) take seconds.

Rows: (day D, story posted in the 72 h before the end of D) for every day with a real list.
Columns: real_rank, prev_list_rank, day_age_h, posted_before_d, base blocks (post, who30, who60, submitter),
text_score (out-of-fold before STAGE1_END, forward after), and for each forecast time T in TIMES (hours before the
end of D): comments so far, in the last 3 h, first-comment delay (vectorised: one sorted search over all comments);
votes so far, rank now, best rank, hours in top 30 / 10, points gained in 3 h (Quality News hourly, where fetched);
stage-1 ranker score per T (ranker trained on days before STAGE1_END).
-> <cache>/daily_cache.parquet

    python daily_cache.py
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import store as S
import top10 as T
import top100 as H

TIMES = {"t12": 12, "t18": 6, "eod": 0}       # name -> hours before the end of day D
STAGE1_END = os.environ.get("STAGE1_END", "2026-09-01")
WINDOW_H = 72
VOTE_MIN_POINTS = float(os.environ.get("VOTE_MIN_POINTS", "30"))
OUT = os.path.join(H.CACHE, os.environ.get("DC_OUT", "daily_cache.parquet"))

L = pd.concat([pd.read_json(os.path.join(H.CACHE, f), lines=True, dtype={"day": str})
               for f in ("frontday.jsonl", "frontday_old.jsonl") + (() if os.environ.get("NO_OLDER") else ("frontday_older.jsonl",))
               if os.path.exists(os.path.join(H.CACHE, f))]).drop_duplicates(["day", "rank"])
L = L.sort_values("rank").drop_duplicates(["day", "post_id"])
p = H.stories()
p = p[p.month >= "2023-03"].reset_index(drop=True)
y = np.log1p(p.points.to_numpy())
born = p.created_at_i.to_numpy().astype(float)

rows = []
for d in sorted(L.day.unique()):
    t1 = pd.Timestamp(d, tz="UTC").timestamp() + 86400
    idx = np.flatnonzero((born >= t1 - WINDOW_H * 3600) & (born < t1))
    rows.append(pd.DataFrame({"day": d, "i": idx, "t1": t1}))
C = pd.concat(rows, ignore_index=True)
C["post_id"] = p.post_id.to_numpy()[C.i]
C["born"] = born[C.i]
C["day_age_h"] = (C.t1 - C.born) / 3600
C["posted_before_d"] = (C.day_age_h > 24).astype(np.int8)
key = pd.MultiIndex.from_frame(C[["day", "post_id"]])
lr = L.set_index(["day", "post_id"])["rank"]
C["list_rank"] = lr.reindex(key).fillna(999).to_numpy()
C["real_rank"] = np.where(C.list_rank <= 30, C.list_rank, 999)
prev = pd.MultiIndex.from_arrays([(pd.to_datetime(C.day) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d"), C.post_id])
C["prev_list_rank"] = lr.reindex(prev).fillna(999).to_numpy()
print("rows", len(C), flush=True)

# comments: one global sorted array keyed by (story position, time)
pos = pd.Series(np.arange(len(p)), index=p.post_id)
cm = H.comments()[["story_id", "created_at_i"]]
cm = cm[cm.story_id.isin(pos.index)]
sp = pos.reindex(cm.story_id).to_numpy()
ct = cm.created_at_i.to_numpy().astype(float)
BIG = 1e10
ck = np.sort(sp * BIG + ct)
start = np.searchsorted(ck, C.i.to_numpy() * BIG)
end = np.searchsorted(ck, (C.i.to_numpy() + 1) * BIG)
first = np.where(end > start, ck[np.minimum(start, len(ck) - 1)] - C.i.to_numpy() * BIG, np.nan)
for name, off in TIMES.items():
    Tt = C.t1.to_numpy() - off * 3600
    n_at = np.searchsorted(ck, C.i.to_numpy() * BIG + Tt) - start
    n_3h = n_at - (np.searchsorted(ck, C.i.to_numpy() * BIG + Tt - 3 * 3600) - start)
    C[f"{name}_c_all"] = n_at
    C[f"{name}_c_last3h"] = n_3h
    C[f"{name}_c_first_h"] = np.where((n_at > 0), (first - C.born) / 3600, 99)
    C[f"{name}_visible"] = (Tt > C.born).astype(np.int8)
    C[f"{name}_age_h"] = (Tt - C.born) / 3600
print("comment features done", flush=True)

# votes: Quality News hourly arrays -> matrices, gathered at each forecast time
qfs = [os.path.join(H.CACHE, f) for f in ("qn_long3.jsonl", "qn_summer.jsonl", "qn_summer_b.jsonl",
                                                 "qn_summer_c.jsonl", "qn_summer_d.jsonl") if os.path.exists(os.path.join(H.CACHE, f))]
if qfs:
    q = pd.concat([pd.read_json(f, lines=True) for f in qfs], ignore_index=True)
    # the summer fetch skipped stories below VOTE_MIN_POINTS final points (no daily top 30 had fewer than 44): count them
    # as covered and give them the no-votes fill (1 point, not on the page) on every day, September included, so train
    # and test match. This uses final points, a small leak; VOTE_MIN_POINTS=0 measures it on fully fetched days.
    lowp = set(p.post_id[(p.points < VOTE_MIN_POINTS).to_numpy()])
    fetched = set(q.post_id) | lowp
    q = q[~q.post_id.isin(lowp)]
    q = q[(q.status == 200) & q.qn_rank_by_hour.map(lambda x: isinstance(x, list))].drop_duplicates("post_id")
    qi = pd.Series(np.arange(len(q)), index=q.post_id)
    RK = np.array([[x if x is not None else 91 for x in r] for r in q.qn_rank_by_hour], float)
    UP = pd.DataFrame([[x for x in r] for r in q.qn_up_by_hour], dtype=float).ffill(axis=1).fillna(1).to_numpy()
    H0 = q.qn_hour0.to_numpy().astype(float)
    row_q = qi.reindex(C.post_id).to_numpy()
    has = ~np.isnan(row_q)
    C["qn_fetched"] = C.post_id.isin(fetched).astype(np.int8)
    for name, off in TIMES.items():
        Tt = C.t1.to_numpy() - off * 3600
        cols = {k: np.full(len(C), np.nan) for k in ("v_points", "v_rank_now", "v_best_rank", "v_h_top30", "v_h_top10", "v_gain3h")}
        r_ = row_q[has].astype(int)
        k = np.clip(((Tt[has] - H0[r_]) // 3600).astype(int), 0, 36)      # hourly slots fully before T
        ok = k > 0
        rr, kk = r_[ok], k[ok]
        idx = np.flatnonzero(has)[ok]
        cols["v_points"][idx] = UP[rr, kk - 1]
        cols["v_rank_now"][idx] = RK[rr, kk - 1]
        cols["v_gain3h"][idx] = UP[rr, kk - 1] - np.where(kk >= 4, UP[rr, np.maximum(kk - 4, 0)], 1)
        mask = np.arange(36)[None, :] < kk[:, None]
        R_ = np.where(mask, RK[rr], 91)
        cols["v_best_rank"][idx] = R_.min(1)
        cols["v_h_top30"][idx] = (R_ <= 30).sum(1)
        cols["v_h_top10"][idx] = (R_ <= 10).sum(1)
        for c_, v_ in cols.items():
            C[f"{name}_{c_}"] = v_
    print("vote features done for", int(has.sum()), "rows", flush=True)

# base blocks and text score
blk = [pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
       .set_index("post_id").reindex(p.post_id).reset_index(drop=True) for b in ["post", "who30", "who60", "submitter"]]
B = pd.concat(blk, axis=1).iloc[C.i].reset_index(drop=True)
B.columns = [f"b_{c}" for c in B.columns]
tr_s, te_s = (p.day < STAGE1_END).to_numpy(), (p.day >= STAGE1_END).to_numpy()
oof, txt = T.text_scores(p, y, tr_s, te_s)
ts = np.full(len(p), np.nan)
ts[tr_s], ts[te_s] = oof, txt
C = pd.concat([C.reset_index(drop=True), B], axis=1)
C["text_score"] = ts[C.i]

# stage-1 rankers (comments only), one per forecast time, trained on days before STAGE1_END
bcols = list(B.columns) + ["text_score", "prev_list_rank", "posted_before_d"]
for name in TIMES:
    fc = bcols + [f"{name}_c_all", f"{name}_c_last3h", f"{name}_c_first_h", f"{name}_age_h"]
    vis = C[f"{name}_visible"].to_numpy() == 1
    tr = (C.day < STAGE1_END).to_numpy() & vis
    sub = C[tr].sort_values("day", kind="stable")
    grp = sub.groupby("day", sort=False).size().to_numpy()
    lab = np.clip(31 - sub.real_rank.to_numpy(), 0, 30).astype(int)
    m = lgb.LGBMRanker(**{**H.GBM, "n_estimators": 500, "n_jobs": os.cpu_count()}, label_gain=list(range(31)))
    m.fit(sub[fc], lab, group=grp)
    C[f"{name}_stage1"] = m.predict(C[fc])
    print("stage 1", name, flush=True)
C.drop(columns=["i"]).to_parquet(OUT, index=False)
print("saved", OUT, C.shape, flush=True)
