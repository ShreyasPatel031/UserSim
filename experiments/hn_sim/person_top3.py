"""Person-level pick accuracy (the research program's simulation-quality metric, same as Product Hunt): for each
person-day in the held-out period (Sep 1 - Oct 14), rank that day's candidate stories for the person (twin_v2 design:
listed stories of the days they were active) and score a hit if one of the top 3 is a story they engaged with.
Random baseline per person-day = 1 - C(n - pos, 3) / C(n, 3). 95% bootstrap intervals over person-days.
Models: content taste (+ favorites), ties to the submitter (ties.py definitions), both, popularity (final points).

    python person_top3.py
"""
import json
import os
from math import comb

import lightgbm as lgb
import numpy as np
import pandas as pd

import top100 as H

CUT, CUT2 = "2026-07-01", "2026-09-01"
t_cut = pd.Timestamp(CUT, tz="UTC").timestamp()
rng = np.random.default_rng(0)
p = H.stories().set_index("post_id")
c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["person", "story_id", "created_at_i"])
c = c[(c.created_at_i < t_cut) & (c.created_at_i >= pd.Timestamp("2025-01-01", tz="UTC").timestamp())]
c["sub"] = c.story_id.map(p.author).to_numpy()
c = c[c["sub"].notna() & (c["sub"] != c.person)]
c["w"] = np.exp(-(t_cut - c.created_at_i.to_numpy()) / (180 * 86400) * np.log(2))
r = pd.read_parquet(os.path.join(H.CACHE, "replies.parquet"))
r = r[(r.t < t_cut) & (r.person != r.parent_author)]
r["w"] = np.exp(-(t_cut - r.t.to_numpy()) / (180 * 86400) * np.log(2))
t_cmt = c.groupby(["person", "sub"]).w.sum()
t_rep = r.groupby(["person", "parent_author"]).w.sum().rename_axis(["person", "sub"])
last = pd.concat([c.groupby(["person", "sub"]).created_at_i.max(),
                  r.groupby(["person", "parent_author"]).t.max().rename_axis(["person", "sub"])]).groupby(level=[0, 1]).max()
back = t_cmt.add(t_rep, fill_value=0)
t_back = back.copy()
t_back.index = t_back.index.swaplevel()
t_back = t_back.rename_axis(["person", "sub"])
act = c.groupby("person").w.sum().add(r.groupby("person").w.sum(), fill_value=0)

D = pd.read_parquet(os.path.join(H.CACHE, "twin_v2_pairs.parquet"))
idx = pd.MultiIndex.from_arrays([D.person.to_numpy(), p.author.reindex(D.story_id).to_numpy()])
D["t_cmt"] = t_cmt.reindex(idx).fillna(0).to_numpy()
D["t_rep"] = t_rep.reindex(idx).fillna(0).to_numpy()
D["t_back"] = t_back.reindex(idx).fillna(0).to_numpy()
D["t_share"] = (D.t_cmt + D.t_rep) / np.maximum(act.reindex(D.person).fillna(0).to_numpy(), 1e-3)
D["t_days_since"] = np.where(last.reindex(idx).notna(), (t_cut - last.reindex(idx).to_numpy()) / 86400, 999)
TIE = ["t_cmt", "t_rep", "t_back", "t_share", "t_days_since", "auth_n"]
CONTENT = ["sim_mean", "sim_max", "sim_top5", "dom_share", "dom_n", "hour_p"] + [x for x in D.columns if x.startswith("fav_")] + (["n_favs"] if "n_favs" in D else [])
tr, te = D[D.day < CUT2].copy(), D[D.day >= CUT2].copy()
# tie standing within the person's options that day (rank of the tie among that day's candidates)
for df in (tr, te):
    df["t_rank_day"] = df.groupby(["person", "day"]).t_cmt.rank(ascending=False) if len(df) else 0
TIE += ["t_rank_day"]


def fit(cols):
    m = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=50, subsample=0.8,
                           subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
    return m.fit(tr[cols], tr.y).predict_proba(te[cols])[:, 1]


def top3(s):
    t = te.assign(s=s + rng.random(len(te)) * 1e-9)
    hits, base = [], []
    for _, g in t.groupby(["person", "day"]):
        n, k = len(g), int(g.y.sum())
        if k == 0 or n < 6:
            continue
        hits.append(float(g.nlargest(3, "s").y.max()))
        base.append(1 - comb(n - k, 3) / comb(n, 3))
    hits, base = np.array(hits), np.array(base)
    b = [rng.choice(hits, len(hits)).mean() for _ in range(1000)]
    return hits.mean(), np.percentile(b, 2.5), np.percentile(b, 97.5), base.mean(), len(hits)


res = {}
for name, cols in (("content taste (+ favorites)", CONTENT), ("ties to the submitter", TIE), ("content + ties", CONTENT + TIE),
                   ("popularity (final points; not known at posting)", ["pop_final"]), ("content + ties + popularity", CONTENT + TIE + ["pop_final"])):
    h, lo, hi, base, n = top3(fit(cols))
    res[name] = {"top3_hit": round(h, 3), "ci95": [round(lo, 3), round(hi, 3)], "random": round(base, 3), "person_days": n}
    print(f"{name:50s} top-3 hit {h:.3f} [{lo:.3f}, {hi:.3f}]  random {base:.3f}  person-days {n}", flush=True)
json.dump(res, open(os.path.join(H.CACHE, "person_top3.json"), "w"), indent=1)
