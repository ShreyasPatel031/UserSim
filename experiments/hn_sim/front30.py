"""Front page = HN's real daily list, top 30 (news.ycombinator.com/front?day=D). Score: share of the real top 30
found in the model's top 30 (and top 10 in top 10), per day, 95% bootstrap over days.

Stage 1: the real-list model (reallist.py setup: candidates posted D-1 12:00 .. end of D; label real rank <= 30),
         trained on days before STAGE1_END (lists from Jan 2025), at a forecast age (60 min or 8 h of comments).
Stage 2: stage-1 score + early upvotes, expected upvotes and top-page rank at 15 / 30 / 60 min (Quality News),
         trained on Quality News days before SPLIT, tested from SPLIT.

    python front30.py [split=2026-09-16]
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

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-16"
STAGE1_END = "2026-08-01"
H.BLOCK_FILES.update({f"early{W}": f"f_early{W}" for W in (120, 240, 480)})

L = pd.concat([pd.read_json(os.path.join(H.CACHE, f), lines=True) for f in ("frontday.jsonl", "frontday_old.jsonl")])
L = L.drop_duplicates(["day", "rank"])
L = L[L["rank"] <= 30]
p = H.stories()
p = p[(p.month >= "2023-03") & (p.month <= "2026-09")].reset_index(drop=True)
y = np.log1p(p.points.to_numpy())
rows = []
for d in sorted(L.day.unique()):
    t1 = pd.Timestamp(d, tz="UTC").timestamp() + 86400
    idx = np.flatnonzero((p.created_at_i >= t1 - 1.5 * 86400).to_numpy() & (p.created_at_i < t1).to_numpy())
    rows.append(pd.DataFrame({"day": d, "i": idx, "h_to_end": (t1 - p.created_at_i.to_numpy()[idx]) / 3600}))
C = pd.concat(rows, ignore_index=True)
real = L.set_index(["day", "post_id"])["rank"]
C["post_id"] = p.post_id.to_numpy()[C.i]
C["real_rank"] = [real.get((d, x), 999) for d, x in zip(C.day, C.post_id)]
C["same_day"] = (p.day.to_numpy()[C.i] == C.day.to_numpy()).astype(int)
blk = {b: pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
       .set_index("post_id").reindex(p.post_id).reset_index(drop=True) for b in
       ["post", "early30", "who30", "early60", "who60", "submitter", "early120", "early240", "early480"]}
tr_s, te_s = (p.day < STAGE1_END).to_numpy(), (p.day >= STAGE1_END).to_numpy()
oof, txt = T.text_scores(p, y, tr_s, te_s)
ts = np.full(len(p), np.nan)
ts[tr_s], ts[te_s] = oof, txt

q = pd.read_json(os.path.join(H.CACHE, "qn_early.jsonl"), lines=True).drop_duplicates("post_id")
q = q[q.status.isin([200, 404])].set_index("post_id")
qcols = [f"qn_{k}{a}" for k in ("up", "exp", "toprank") for a in (15, 30, 60)]
fill = {f"qn_up{a}": 1 for a in (15, 30, 60)} | {f"qn_toprank{a}": 91 for a in (15, 30, 60)}
base = ["post", "early30", "who30", "early60", "who60", "submitter"]
rng = np.random.default_rng(0)
out = []


def score(P, col):
    r = {}
    for k in (30, 10):
        v = [len(set(g[g.real_rank <= k].post_id) & set(g.nlargest(k, col).post_id)) / k for _, g in P.groupby("day")]
        r[f"real{k}_in_top{k}"] = R.boot(v)
    v = [len(set(g[g.real_rank <= 30].post_id) & set(g.nlargest(100, col).post_id)) / 30 for _, g in P.groupby("day")]
    r["real30_in_top100"] = R.boot(v)
    return r


for age, cols in (("60 min", base), ("8 h", base + ["early120", "early240", "early480"])):
    X = pd.concat([blk[b] for b in cols], axis=1).iloc[C.i].reset_index(drop=True)
    X = X.assign(text_score=ts[C.i], h_to_end=C.h_to_end.to_numpy(), same_day=C.same_day.to_numpy())
    tr, te = (C.day < STAGE1_END).to_numpy(), (C.day >= STAGE1_END).to_numpy()
    c1 = lgb.LGBMClassifier(**{**H.GBM, "scale_pos_weight": 3}).fit(X[tr], (C.real_rank[tr] <= 30).astype(int))
    D = C[te][["day", "post_id", "real_rank"]].assign(stage1=c1.predict_proba(X[te])[:, 1])
    Q = q.reindex(D.post_id)
    for c in qcols:
        D[c] = Q[c].to_numpy()
    D = D[D.post_id.isin(q.index)]
    n = D.groupby("day").size()
    D = D[D.day.isin(n[n >= 500].index)].fillna(fill)
    for c in qcols:
        D[c] = D[c].fillna(D[c].median())
    trd, ted = D[D.day < SPLIT], D[D.day >= SPLIT]
    c2 = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8,
                            subsample_freq=1, verbose=-1, random_state=0).fit(trd[["stage1"] + qcols], (trd.real_rank <= 30).astype(int))
    ted = ted.assign(stage2=c2.predict_proba(ted[["stage1"] + qcols])[:, 1], up60=ted.qn_up60)
    print(f"{age}: QN days train {trd.day.nunique()} test {ted.day.nunique()}", flush=True)
    for col, name in (("stage1", f"{age}: real-list model"), ("up60", "upvotes at 60 min only"),
                      ("stage2", f"{age}: real-list model + early upvotes and rank")):
        r = score(ted, col)
        print(name, json.dumps(r), flush=True)
        out += [{"kind": "front30", "variant": name, "metric": k, "value": v[0], "lo": v[1], "hi": v[2],
                 "test_days": int(ted.day.nunique()), "made_on": S.now()} for k, v in r.items()]
S.write("hn_scores", pd.DataFrame(out))
