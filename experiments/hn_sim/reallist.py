"""Train on HN's real daily list (news.ycombinator.com/front?day=D, frontday.py) instead of points.

For day D the candidates are stories posted from D-1 12:00 UTC to the end of D (the real list also holds stories from
the day before). Label: in the real list's top 30 that day. A story can be a candidate on two days (two rows).
Features: the scoreboard blocks at a forecast age (60 min, or 8 h for the late-bloomer variant), plus the hours
between posting and the end of day D. Test months 2026-05..09, each trained on earlier days (lists from Jan 2025).
Compared on the same candidate pools with the points-trained model (label: day's top 100 by points).
Metrics: real top 10 / top 30 found in the model's top 10 / 30 / 100.

    python reallist.py
"""
import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import store as S
import top10 as T
import top100 as H

TEST = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
H.BLOCK_FILES.update({f"early{W}": f"f_early{W}" for W in (120, 240, 480)})
fl = [pd.read_json(os.path.join(H.CACHE, f), lines=True) for f in ("frontday.jsonl", "frontday_old.jsonl")
      if os.path.exists(os.path.join(H.CACHE, f))]
L = pd.concat(fl).drop_duplicates(["day", "rank"])
L = L[L["rank"] <= 30]
print("days with a real list:", L.day.nunique(), L.day.min(), L.day.max(), flush=True)
p = H.stories()
p = p[p.month >= "2023-03"].reset_index(drop=True)          # text model and records use the full history
y = np.log1p(p.points.to_numpy())
rkp = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
# candidate rows: (day D, story) for stories posted in [D-1 12:00, D+1 00:00)
rows = []
for d in sorted(L.day.unique()):
    t1 = pd.Timestamp(d, tz="UTC").timestamp() + 86400
    idx = np.flatnonzero((p.created_at_i >= t1 - 1.5 * 86400).to_numpy() & (p.created_at_i < t1).to_numpy())
    rows.append(pd.DataFrame({"day": d, "i": idx, "h_to_end": (t1 - p.created_at_i.to_numpy()[idx]) / 3600}))
C = pd.concat(rows, ignore_index=True)
real = L.set_index(["day", "post_id"])["rank"]
C["post_id"] = p.post_id.to_numpy()[C.i]
C["real_rank"] = [real.get((d, x), 999) for d, x in zip(C.day, C.post_id)]
C["month"] = C.day.str[:7]
print("candidate rows", len(C), "positives", int((C.real_rank <= 30).sum()), flush=True)
blk = {b: pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
       .set_index("post_id").reindex(p.post_id).reset_index(drop=True) for b in
       ["post", "early30", "who30", "early60", "who60", "submitter", "early120", "early240", "early480"]}
base = ["post", "early30", "who30", "early60", "who60", "submitter"]
rng = np.random.default_rng(0)
out_rows = []
for age, cols in (("60 min", base), ("8 h", base + ["early120", "early240", "early480"])):
    Xs = pd.concat([blk[b] for b in cols], axis=1)
    res = []
    for m in TEST:
        # text score: out-of-fold for stories before the test month, forward for stories in it
        tr_s, te_s = (p.month < m).to_numpy(), (p.month == m).to_numpy()
        oof, txt = T.text_scores(p, y, tr_s, te_s)
        ts = np.full(len(p), np.nan)
        ts[tr_s], ts[te_s] = oof, txt
        X = Xs.iloc[C.i].reset_index(drop=True).assign(text_score=ts[C.i], h_to_end=C.h_to_end.to_numpy())
        tr, te = (C.month < m).to_numpy(), (C.month == m).to_numpy()
        clf = lgb.LGBMClassifier(**{**H.GBM, "scale_pos_weight": 3})
        s_real = clf.fit(X[tr], (C.real_rank[tr] <= 30).astype(int)).predict_proba(X[te])[:, 1]
        # points-trained baseline on the same rows (label: story's own day top 100 by points)
        lab_p = (rkp[C.i] <= 100).astype(int)
        s_pts = lgb.LGBMClassifier(**{**H.GBM, "scale_pos_weight": 2}).fit(X[tr], lab_p[tr]).predict_proba(X[te])[:, 1]
        res.append(C[te][["day", "post_id", "real_rank"]].assign(s_real=s_real, s_pts=s_pts))
        print(age, m, flush=True)
    P = pd.concat(res, ignore_index=True)
    for col in ("s_pts", "s_real"):
        r = {}
        for k, n in ((10, 10), (10, 30), (10, 100), (30, 30), (30, 100)):
            v = [len(set(g[g.real_rank <= k].post_id) & set(g.nlargest(n, col).post_id)) / k for _, g in P.groupby("day")]
            r[f"real{k}_in_top{n}"] = R.boot(v)
        name = f"{age}, trained on {'real list' if col == 's_real' else 'points'}"
        print(name, json.dumps(r), flush=True)
        out_rows += [{"kind": "reallist", "variant": name, "metric": k, "value": v[0], "lo": v[1], "hi": v[2],
                      "days": int(P.day.nunique()), "made_on": S.now()} for k, v in r.items()]
S.write("hn_scores", pd.DataFrame(out_rows))
