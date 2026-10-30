"""Final model choice on the scoreboard months (2026-05..09, top 100 / 30 / 10 by points):
classifier vs per-day ranker, with and without comment acceleration, at forecast ages 60 min and 8 h.

Acceleration (fixed): counts only comments inside the first 60 min (0-15 / 15-30 / 30-60 min) and ratios of
consecutive windows, with stories that have no comment in that hour filled the same way whether or not they get
comments later (model_a.py's version filled never-commented stories differently: a leak of the outcome)."""
import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import store as S
import top10 as T
import top100 as H

H.BLOCK_FILES.update({f"early{W}": f"f_early{W}" for W in (120, 240, 480)})
p = H.stories()
p = p[(p.month >= "2023-03") & (p.month <= H.TEST[-1])].reset_index(drop=True)
y = np.log1p(p.points.to_numpy())
rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()

c = H.comments()
born = pd.Series(p.created_at_i.to_numpy(), index=p.post_id)
c = c[c.story_id.isin(born.index)]
c["age"] = c.created_at_i - c.story_id.map(born).to_numpy()
c = c[(c.age >= 0) & (c.age <= 3600)]
g = c.groupby("story_id").age
acc = pd.DataFrame({"a_0_15": g.apply(lambda a: (a <= 900).sum()), "a_15_30": g.apply(lambda a: ((a > 900) & (a <= 1800)).sum()),
                    "a_30_60": g.apply(lambda a: (a > 1800).sum())}).reindex(p.post_id).fillna(0).reset_index(drop=True)
acc["a_ratio"] = (acc.a_15_30 + 1) / (acc.a_0_15 + 1)
acc["a_ratio2"] = (acc.a_30_60 + 1) / (acc.a_15_30 + 1)
print("accel built", flush=True)

blk = {b: pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
       .set_index("post_id").reindex(p.post_id).reset_index(drop=True) for b in
       ["post", "early30", "who30", "early60", "who60", "submitter", "early120", "early240", "early480"]}
blk["accel"] = acc
base = ["post", "early30", "who30", "early60", "who60", "submitter"]
late = base + ["early120", "early240", "early480"]
keep = (rk <= 100) | (np.random.default_rng(0).random(len(p)) < 0.25)
texts = {m: T.text_scores(p, y, (p.month < m).to_numpy(), (p.month == m).to_numpy()) for m in H.TEST}
rng = np.random.default_rng(0)
rows = []
for name, cols, kind in (("60 min clf", base, "clf"), ("60 min clf +accel", base + ["accel"], "clf"),
                         ("60 min rank", base, "rank"), ("60 min rank +accel", base + ["accel"], "rank"),
                         ("8 h clf", late, "clf"), ("8 h rank", late, "rank")):
    X = pd.concat([blk[b] for b in cols], axis=1)
    res = []
    for m in H.TEST:
        tr, te = (p.month < m).to_numpy(), (p.month == m).to_numpy()
        oof, txt = texts[m]
        Xtr, Xte = X[tr].assign(text_score=oof), X[te].assign(text_score=txt)
        if kind == "rank":
            d = p.day[tr].to_numpy()
            grp = np.diff(np.flatnonzero(np.r_[True, d[1:] != d[:-1], True]))
            lab = np.clip(101 - rk[tr], 0, 100).astype(int) // 10
            s = lgb.LGBMRanker(**{**H.GBM, "n_estimators": 400}, label_gain=[2 ** i - 1 for i in range(11)]).fit(
                Xtr, lab, group=grp).predict(Xte)
        else:
            k = keep[tr]
            s = lgb.LGBMClassifier(**{**H.GBM, "scale_pos_weight": 2}).fit(Xtr[k], (rk[tr][k] <= 100).astype(int)).predict_proba(Xte)[:, 1]
        res.append(pd.DataFrame({"day": p.day[te].to_numpy(), "y": y[te], "s": s}))
    P = pd.concat(res, ignore_index=True)
    r = {k: R.boot(T.day_hits(P, "s", k, rng)) for k in (100, 30, 10)}
    rows += [{"kind": "ladder", "variant": f"final: {name}", "k": k, "recall": v[0], "lo": v[1], "hi": v[2], "data": "bq2023",
              "test": f"{H.TEST[0]}..{H.TEST[-1]}", "days": int(P.day.nunique()), "made_on": S.now()} for k, v in r.items()]
    print(name, json.dumps(r), flush=True)
S.write("hn_scores", pd.DataFrame(rows))
