"""Workstream A: core-model improvements on the top-100 scoreboard (top100.py data, same test months and scoring).

Blocks:
  whotopic{W}  each early commenter's past record on stories in the SAME topic (k-means over title vectors, 64
               topics, fit on stories before each test month), plus recency-weighted overall record (half-life 90 d)
  accel        comment arrival shape: comments in 0-15 vs 15-30 vs 30-60 min, distinct people per comment
Model variants:  clf (top100.ladder's classifier), big (more trees / leaves), rank (LambdaRank per day)

    python model_a.py build
    python model_a.py run
"""
from __future__ import annotations

import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

import rank as R
import store as S
import top10 as T
import top100 as H

CACHE = S.LOCAL


def build(W: int = 30) -> None:
    p = H.stories()
    c = H.comments()
    born = pd.Series(p.created_at_i.to_numpy(), index=p.post_id)
    c = c[c.story_id.isin(born.index)]
    c["age"] = c.created_at_i - c.story_id.map(born).to_numpy()
    c = c[c.age >= 0]
    # accel block
    g = c.groupby("story_id")
    acc = pd.DataFrame({"a_0_15": g.age.apply(lambda a: (a <= 900).sum()),
                        "a_15_30": g.age.apply(lambda a: ((a > 900) & (a <= 1800)).sum()),
                        "a_30_60": g.age.apply(lambda a: ((a > 1800) & (a <= 3600)).sum())})
    acc["a_ratio"] = (acc.a_15_30 + 1) / (acc.a_0_15 + 1)
    acc["a_ratio2"] = (acc.a_30_60 + 1) / (acc.a_15_30 + 1)
    acc = acc.reindex(p.post_id).fillna(0).reset_index().rename(columns={"story_id": "post_id", "index": "post_id"})
    acc.to_parquet(os.path.join(CACHE, "f_accel.parquet"), index=False)
    print("accel built", flush=True)
    # whotopic block
    e = c[c.age <= W * 60].drop_duplicates(["person", "story_id"])[["person", "story_id"]].copy()
    e["t"] = e.story_id.map(born).to_numpy()
    rk = p.groupby("day").points.rank(ascending=False, method="first")
    e["h"] = e.story_id.map(pd.Series((rk <= 100).to_numpy(), index=p.post_id)).astype(float).to_numpy()
    out = []
    months = sorted(m for m in p.month.unique() if m >= "2023-03")
    for m in months:
        t0 = H.month_t0(m)
        old = p[(p.created_at_i < t0) & (p.created_at_i >= t0 - 365 * 86400)]
        tf = TfidfVectorizer(min_df=5, sublinear_tf=True, max_features=100000).fit(old.title)
        svd = TruncatedSVD(64, random_state=0).fit(tf.transform(old.title.sample(min(len(old), 150000), random_state=0)))
        km = MiniBatchKMeans(64, random_state=0, n_init=3, batch_size=4096)
        km.fit(svd.transform(tf.transform(old.title.sample(min(len(old), 150000), random_state=1))))
        sel = p[(p.created_at_i >= t0 - 730 * 86400) & (p.month <= m)]
        topic = pd.Series(km.predict(svd.transform(tf.transform(sel.title))), index=sel.post_id)
        past = e[(e.t < t0 - 2 * 86400) & (e.t >= t0 - 730 * 86400)].copy()
        past["topic"] = past.story_id.map(topic).to_numpy()
        prior = past.h.mean()
        pt = past.groupby(["person", "topic"]).h.agg(["sum", "count"])
        lt = (pt["sum"] + 5 * prior) / (pt["count"] + 5) / prior
        wgt = 0.5 ** ((t0 - past.t) / (90 * 86400))
        past["wh"], past["w"] = past.h * wgt, wgt
        rr = past.groupby("person")[["wh", "w"]].sum()
        lr = (rr.wh + 5 * prior) / (rr.w + 5) / prior
        cur = e[e.story_id.isin(p.post_id[p.month == m])].copy()
        cur["topic"] = cur.story_id.map(topic).to_numpy()
        cur["lt"] = pd.Series(list(zip(cur.person, cur.topic))).map(lt).fillna(1.0).to_numpy()
        cur["lr"] = cur.person.map(lr).fillna(1.0).to_numpy()
        g = cur.groupby("story_id")
        out.append(pd.DataFrame({f"wt{W}_topic_max": g.lt.max(), f"wt{W}_topic_sum": g.lt.sum(),
                                 f"wt{W}_recent_max": g.lr.max(), f"wt{W}_recent_sum": g.lr.sum()}))
        print("whotopic", m, flush=True)
    f = pd.concat(out).reindex(p.post_id).fillna(0).reset_index().rename(columns={"story_id": "post_id", "index": "post_id"})
    f.to_parquet(os.path.join(CACHE, f"f_whotopic{W}.parquet"), index=False)


def run() -> None:
    """Scoreboard: base = post+early30+who30 (+60-min blocks), then +whotopic30, +accel, and model variants."""
    H.BLOCK_FILES.update({"whotopic30": "f_whotopic30", "accel": "f_accel"})
    p = H.stories()
    p = p[p.month <= H.TEST[-1]].reset_index(drop=True)
    y = np.log1p(p.points.to_numpy())
    rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
    blocks = {}
    names = ["post", "early30", "who30", "early60", "who60", "submitter", "whotopic30", "accel"]
    for b in names:
        f = pd.read_parquet(os.path.join(CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
        blocks[b] = f.set_index("post_id").reindex(p.post_id).reset_index(drop=True)
    rng = np.random.default_rng(0)
    keep = (rk <= H.TARGET) | (rng.random(len(p)) < 0.25)
    texts = {m: T.text_scores(p, y, (p.month < m).to_numpy() & (p.month >= "2023-03").to_numpy(), (p.month == m).to_numpy())
             for m in H.TEST}
    variants = {
        "A: post+30min (clf)": (["post", "early30", "who30"], "clf"),
        "A: +whotopic30": (["post", "early30", "who30", "whotopic30"], "clf"),
        "A: +accel": (["post", "early30", "who30", "whotopic30", "accel"], "clf"),
        "A: 60min all (clf)": (names, "clf"),
        "A: 60min all (big)": (names, "big"),
        "A: 60min all (rank)": (names, "rank"),
    }
    rows = []
    for name, (cols, kind) in variants.items():
        X = pd.concat([blocks[b] for b in cols], axis=1)
        res = []
        for m in H.TEST:
            tr = (p.month < m).to_numpy() & (p.month >= "2023-03").to_numpy()
            te = (p.month == m).to_numpy()
            oof, txt = texts[m]
            Xtr, Xte = X[tr].assign(text_score=oof), X[te].assign(text_score=txt)
            if kind == "rank":
                d = p.day[tr].to_numpy()
                grp = np.diff(np.flatnonzero(np.r_[True, d[1:] != d[:-1], True]))
                lab = np.clip(101 - rk[tr], 0, 100).astype(int) // 10            # graded: 10 bands over the top 100
                mdl = lgb.LGBMRanker(**{**H.GBM, "n_estimators": 400}, label_gain=[2 ** i - 1 for i in range(11)])
                s = mdl.fit(Xtr, lab, group=grp).predict(Xte)
            else:
                prm = {**H.GBM, "scale_pos_weight": 2}
                if kind == "big":
                    prm.update(n_estimators=900, learning_rate=0.03, num_leaves=127, min_child_samples=100)
                k = keep[tr]
                s = lgb.LGBMClassifier(**prm).fit(Xtr[k], (rk[tr][k] <= H.TARGET).astype(int)).predict_proba(Xte)[:, 1]
            res.append(pd.DataFrame({"day": p.day[te].to_numpy(), "y": y[te], "s": s}))
        P = pd.concat(res, ignore_index=True)
        r = {k: R.boot(T.day_hits(P, "s", k, rng)) for k in (100, 30, 10)}
        rows += [{"kind": "ladder", "variant": name, "k": k, "recall": v[0], "lo": v[1], "hi": v[2], "data": "bq2023",
                  "test": f"{H.TEST[0]}..{H.TEST[-1]}", "days": int(P.day.nunique()), "made_on": S.now()}
                 for k, v in r.items()]
        print(name, json.dumps(r), flush=True)
    S.write("hn_scores", pd.DataFrame(rows))


if __name__ == "__main__":
    {"build": build, "run": run}[sys.argv[1]]()
