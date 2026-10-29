"""Does modelling the people add to the daily top-10 forecast? Test months 2026-05..2026-09 (BigQuery data ends Oct 17),
each trained on everything before it. Variants (same classifier: made the day's top 30):
  post_only           title, domain, author, timing (top10.feats)
  + crowd             expected commenters tallied over the 20,000 most active people (crowd.py)
  + early30           top-level comments in the first 30 minutes (count)
  + early30_who       ...plus WHO they were: each early commenter's past record of turning up early on stories that
                      made the day's top 30 (smoothed, from stories finished before the test month only)
  + all
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import store as S
import top10 as T

MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
p = T.stories()
p = p[p.day < "2026-10-01"].reset_index(drop=True)
F = T.feats(p)
E = S.read("hn_scores")
E = E[E.kind == "early"].drop_duplicates("post_id").set_index("post_id")
F["c30"] = p.post_id.map(E["c30"]).fillna(0).to_numpy()
G = pd.read_parquet(os.path.join(S.LOCAL, "crowd_features.parquet")).drop_duplicates("post_id").set_index("post_id")
F["crowd_tally"] = p.post_id.map(G.crowd_tally).to_numpy()
F["crowd_regulars"] = p.post_id.map(G.crowd_regulars).to_numpy()
y = np.log1p(p.points.to_numpy())
rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
top30 = dict(zip(p.post_id, rk <= 30))
born = dict(zip(p.post_id, p.created_at_i))

C = pd.read_parquet(os.path.join(S.LOCAL, "crowd_comments.parquet"))
C = C[C.story_id.notna() & (C.top_level == 1)]
C["story_id"] = C.story_id.astype(int)
C = C[C.story_id.isin(born.keys())]
C["age"] = C.created_at_i - C.story_id.map(born)
early = C[(C.age >= 0) & (C.age <= 1800)].drop_duplicates(["person", "story_id"])
early["hit"] = early.story_id.map(top30).astype(float)


def who_features(m: str) -> pd.DataFrame:
    """For stories in month m: early commenters' smoothed past hit rate (mean, max, sum over the 30-min commenters)."""
    t0 = int(pd.Timestamp(m + "-01", tz="UTC").timestamp())
    past = early[early.story_id.map(born) < t0 - 2 * 86400]
    prior = past.hit.mean()
    rec = past.groupby("person").hit.agg(["sum", "count"])
    rate = (rec["sum"] + 5 * prior) / (rec["count"] + 5)          # smoothed toward the base rate
    cur = early[early.story_id.isin(p.post_id[p.month == m])].copy()
    cur["rate"] = cur.person.map(rate).fillna(prior)
    cur["lift"] = cur.rate / prior
    return cur.groupby("story_id").agg(who_mean=("lift", "mean"), who_max=("lift", "max"), who_sum=("lift", "sum"))


START = "2025-05"   # crowd and who features exist from here; every variant trains on months >= START
W = pd.concat([who_features(m) for m in sorted(p.month.unique()) if m >= START])
for c in ("who_mean", "who_max", "who_sum"):
    F[c] = p.post_id.map(W[c]).fillna(0).to_numpy()

base = [c for c in F.columns if c not in ("c30", "crowd_tally", "crowd_regulars", "who_mean", "who_max", "who_sum")]
V = {"post_only": base, "+crowd": base + ["crowd_tally", "crowd_regulars"], "+early30": base + ["c30"],
     "+early30_who": base + ["c30", "who_mean", "who_max", "who_sum"],
     "+all": base + ["c30", "who_mean", "who_max", "who_sum", "crowd_tally", "crowd_regulars"]}
rng = np.random.default_rng(0)
out = []
for m in MONTHS:
    tr, te = (p.month < m).to_numpy(), (p.month == m).to_numpy()
    oof, txt = T.text_scores(p, y, tr, te)
    res = {"day": p.day[te].to_numpy(), "y": y[te]}
    for name, cols in V.items():
        trm = tr & (p.month >= START).to_numpy()
        c = lgb.LGBMClassifier(**{**T.GBM, "scale_pos_weight": 5})
        c.fit(F[trm][cols].assign(text_score=oof[trm[tr]]), (rk[trm] <= 30).astype(int))
        res[name] = c.predict_proba(F[te][cols].assign(text_score=txt))[:, 1]
    out.append(pd.DataFrame(res))
    print(m, flush=True)
P = pd.concat(out, ignore_index=True).dropna()
print("test days", P.day.nunique())
for name in V:
    print(name, {k: R.boot(T.day_hits(P, name, k, rng)) for k in (10, 30)})
