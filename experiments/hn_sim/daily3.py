"""Daily list v3 = v2 (daily2.py: real-list ranker on comments by forecast time + previous-day list) + votes over the
day from Quality News hourly snapshots (qn_long3.jsonl: rank on HN's front page and upvotes at the end of each UTC
hour). For a forecast at time T on day D, per candidate story: points at T, front-page rank at T, best rank before T,
hours in the top 30 / top 10 before T, points gained in the last 3 h.

Stage 1: the v2 ranker trained on days before STAGE1_END. Stage 2: small ranker on [stage-1 score + vote inputs],
trained on Quality News days before SPLIT and tested from SPLIT (only days whose candidates are all covered).

    python daily3.py [split]
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import store as S
import top10 as T
import top100 as H

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-23"
STAGE1_END = "2026-09-01"
WINDOW_H = 72
L = pd.concat([pd.read_json(os.path.join(H.CACHE, f), lines=True, dtype={"day": str})
               for f in ("frontday.jsonl", "frontday_old.jsonl")]).drop_duplicates(["day", "rank"])
L = L.sort_values("rank").drop_duplicates(["day", "post_id"])
p = H.stories()
p = p[p.month >= "2023-03"].reset_index(drop=True)
y = np.log1p(p.points.to_numpy())
born = p.created_at_i.to_numpy()
rows = []
for d in sorted(L.day.unique()):
    t1 = pd.Timestamp(d, tz="UTC").timestamp() + 86400
    idx = np.flatnonzero((born >= t1 - WINDOW_H * 3600) & (born < t1))
    rows.append(pd.DataFrame({"day": d, "i": idx}))
C = pd.concat(rows, ignore_index=True)
C["post_id"] = p.post_id.to_numpy()[C.i]
C["t1"] = pd.to_datetime(C.day, utc=True).map(lambda x: x.timestamp()).to_numpy() + 86400
C["day_age_h"] = (C.t1 - born[C.i]) / 3600
C["posted_before_d"] = (C.day_age_h > 24).astype(int)
real = L[L["rank"] <= 30].set_index(["day", "post_id"])["rank"]
allrank = L.set_index(["day", "post_id"])["rank"]
C["real_rank"] = [real.get((d, x), 999) for d, x in zip(C.day, C.post_id)]
prev = (pd.to_datetime(C.day) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
C["prev_list_rank"] = [allrank.get((d, x), 999) for d, x in zip(prev, C.post_id)]

cm = H.comments()[["story_id", "person", "created_at_i"]]
cm = cm[cm.story_id.isin(set(C.post_id))].sort_values(["story_id", "created_at_i"])
ct = {k: v.to_numpy() for k, v in cm.groupby("story_id").created_at_i}

q = pd.read_json(os.path.join(H.CACHE, "qn_long3.jsonl"), lines=True)
q = q[q.status == 200].drop_duplicates("post_id")
QR = {r.post_id: (r.qn_hour0, r.qn_rank_by_hour, r.qn_up_by_hour) for r in q.itertuples()
      if isinstance(r.qn_rank_by_hour, list)}
qdone = set(q.post_id) | set(pd.read_json(os.path.join(H.CACHE, "qn_long3.jsonl"), lines=True).post_id)


def comment_feats(T_off):
    out = np.zeros((len(C), 3))
    for r, (pid, t1) in enumerate(zip(C.post_id.to_numpy(), C.t1.to_numpy())):
        ts = ct.get(pid)
        if ts is None:
            continue
        T_ = t1 - T_off * 3600
        n = np.searchsorted(ts, T_)
        out[r] = (n, n - np.searchsorted(ts, T_ - 3 * 3600), (ts[0] - born[C.i.iat[r]]) / 3600 if n else 99)
    return pd.DataFrame(out, columns=["c_all", "c_last3h", "c_first_h"])


def vote_feats(T_off):
    out = np.full((len(C), 6), np.nan)
    for r, (pid, t1) in enumerate(zip(C.post_id.to_numpy(), C.t1.to_numpy())):
        v = QR.get(pid)
        if v is None:
            continue
        h0, rk, up = v
        T_ = t1 - T_off * 3600
        k = int((T_ - h0) // 3600)            # hourly slots fully before T
        if k <= 0:
            continue
        rk_ = np.array([x if x is not None else 91 for x in rk[:k]], float)
        up_ = pd.Series([x for x in up[:k]], dtype=float).ffill().fillna(1).to_numpy()
        out[r] = (up_[-1], rk_[-1], rk_.min(), (rk_ <= 30).sum(), (rk_ <= 10).sum(), up_[-1] - (up_[-4] if k >= 4 else 1))
    return pd.DataFrame(out, columns=["v_points", "v_rank_now", "v_best_rank", "v_h_top30", "v_h_top10", "v_gain3h"])


blk = {b: pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
       .set_index("post_id").reindex(p.post_id).reset_index(drop=True) for b in ["post", "who30", "who60", "submitter"]}
base = pd.concat([blk[b] for b in blk], axis=1).iloc[C.i].reset_index(drop=True)
tr_s, te_s = (p.day < STAGE1_END).to_numpy(), (p.day >= STAGE1_END).to_numpy()
oof, txt = T.text_scores(p, y, tr_s, te_s)
ts = np.full(len(p), np.nan)
ts[tr_s], ts[te_s] = oof, txt


def ranker_fit(X, lab_rank, days, n=500, leaves=None):
    o = np.argsort(days, kind="stable")
    d = days[o]
    grp = np.diff(np.flatnonzero(np.r_[True, d[1:] != d[:-1], True]))
    prm = {**H.GBM, "n_estimators": n}
    if leaves:
        prm.update(num_leaves=leaves, min_child_samples=10)
    return lgb.LGBMRanker(**prm, label_gain=list(range(31))).fit(X.iloc[o], np.clip(31 - lab_rank[o], 0, 30).astype(int), group=grp)


def score(P, col):
    r = {}
    for k, n in ((30, 30), (10, 10), (10, 30)):
        v = [len(set(g[g.real_rank <= k].post_id) & set(g.nlargest(n, col).post_id)) / k for _, g in P.groupby("day")]
        r[f"real{k}_in_top{n}"] = R.boot(v)
    return r


out_rows = []
for label, T_off in (("12:00 UTC", 12), ("18:00 UTC", 6), ("end of day", 0)):
    visible = (C.t1 - T_off * 3600 > born[C.i]).to_numpy()
    X = pd.concat([base, comment_feats(T_off)], axis=1).assign(
        day_age_h=C.day_age_h.to_numpy() - T_off, posted_before_d=C.posted_before_d, prev_list_rank=C.prev_list_rank,
        text_score=ts[C.i])
    tr = (C.day < STAGE1_END).to_numpy() & visible
    te = (C.day >= STAGE1_END).to_numpy() & visible
    m1 = ranker_fit(X[tr].reset_index(drop=True), C.real_rank.to_numpy()[tr], C.day.to_numpy()[tr])
    D = C[te][["day", "post_id", "real_rank"]].reset_index(drop=True).assign(stage1=m1.predict(X[te]))
    V = vote_feats(T_off)[te].reset_index(drop=True)
    D = pd.concat([D, V], axis=1)
    cov = D.groupby("day").post_id.apply(lambda s: np.mean([x in qdone for x in s]))
    D = D[D.day.isin(cov[cov >= 0.98].index)]                 # days whose candidates were all fetched
    vc = list(V.columns)
    D[vc] = D[vc].fillna({"v_points": 1, "v_rank_now": 91, "v_best_rank": 91, "v_h_top30": 0, "v_h_top10": 0, "v_gain3h": 0})
    trd, ted = D[D.day < SPLIT], D[D.day >= SPLIT]
    if trd.day.nunique() < 3 or ted.day.nunique() < 3:
        print(label, "not enough covered days yet:", sorted(D.day.unique()), flush=True)
        continue
    m2 = ranker_fit(trd[["stage1"] + vc].reset_index(drop=True), trd.real_rank.to_numpy(), trd.day.to_numpy(), n=300, leaves=15)
    ted = ted.assign(stage2=m2.predict(ted[["stage1"] + vc]), rank_now=-ted.v_rank_now)
    print(f"{label}: stage-2 train days {trd.day.nunique()}, test days {ted.day.nunique()}", flush=True)
    for col, name in (("stage1", "v2 (comments)"), ("rank_now", "HN's live rank at T only"), ("stage2", "v3 = v2 + votes and rank")):
        r = score(ted, col)
        print(f"{label} | {name}", json.dumps(r), flush=True)
        out_rows += [{"kind": "daily_list_v3", "variant": f"{label} | {name}", "metric": k, "value": v[0], "lo": v[1],
                      "hi": v[2], "days": int(ted.day.nunique()), "made_on": S.now()} for k, v in r.items()]
if out_rows:
    S.write("hn_scores", pd.DataFrame(out_rows))
