"""Crowd model: model each active HN commenter, predict who engages with each new story, tally.

Per test month M (everything uses only comments before M starts):
  people   the TOP most active commenters in the 120 days before M
  profile  topic vector = mean of the title vectors (TF-IDF + SVD, 128 dims, fit on stories before M) of the stories
           they commented on; activity = comments in the 30 days before M; hour profile = share of comments per UTC hour
  p(u, s)  logistic model of "u comments on s" from (topic match, activity, hour match, regular-of-domain),
           fit on the month before M (profiles built before that month), sampled negatives, intercept corrected
  tally    expected commenters per story = sum over people of p(u, s); plus the count of regulars likely to engage
Comments stand in for votes (HN votes are not public). Output: per-story crowd features for every month, saved to
<cache>/crowd_features.parquet, then scored by crowd_exp.py.

    python crowd.py 2025-04 2026-10
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

import store as S
import top10 as T

TOP = 20000
DIM = 128
NEG = 20


def month_start(m: str) -> int:
    return int(pd.Timestamp(m + "-01", tz="UTC").timestamp())


def doc(p: pd.DataFrame) -> pd.Series:
    host = p.url.fillna("").str.replace(r"https?://(www\.)?", "", regex=True).str.split("/").str[0]
    return p.title.fillna("") + " " + host


def profiles(C: pd.DataFrame, V: dict, t0: int):
    """People active before t0: index, topic vectors U, activity a, hour profile H."""
    w = C[(C.created_at_i < t0) & (C.created_at_i >= t0 - 120 * 86400)]
    top = w.person.value_counts().head(TOP).index
    w = w[w.person.isin(top) & w.story_id.isin(V.keys())]
    idx = {u: i for i, u in enumerate(top)}
    U = np.zeros((len(top), DIM), np.float32)
    rows = w.person.map(idx).to_numpy()
    vecs = np.stack([V[s] for s in w.story_id.to_numpy()])
    np.add.at(U, rows, vecs)
    U /= np.linalg.norm(U, axis=1, keepdims=True) + 1e-9
    a = np.bincount(w[w.created_at_i >= t0 - 30 * 86400].person.map(idx), minlength=len(top)).astype(np.float32)
    H = np.zeros((len(top), 24), np.float32)
    np.add.at(H, (rows, ((w.created_at_i.to_numpy() // 3600) % 24).astype(int)), 1)
    H /= H.sum(1, keepdims=True) + 1e-9
    return idx, U, a, H


def pair_x(aff, a, Hh):
    return np.stack([aff, np.log1p(a), Hh * 24, aff * np.log1p(a)], -1)


def main(first: str, last: str) -> None:
    p = T.stories()
    C = pd.read_parquet(os.path.join(S.LOCAL, "crowd_comments.parquet"))
    C = C[C.story_id.notna()]
    C["story_id"] = C.story_id.astype(int)
    months = [m for m in sorted(p.month.unique()) if first <= m <= last]
    out = []
    for m in months:
        t0 = month_start(m)
        prev = (pd.Timestamp(m + "-01") - pd.offsets.MonthBegin(1)).strftime("%Y-%m")
        t_1 = month_start(prev)
        old = p[p.created_at_i < t0]
        tf = TfidfVectorizer(min_df=5, ngram_range=(1, 2), sublinear_tf=True, max_features=200000)
        X = tf.fit_transform(doc(old))
        svd = TruncatedSVD(DIM, random_state=0).fit(X[-200000:])
        cur = p[(p.created_at_i >= t_1) & (p.month <= m)]
        allv = svd.transform(tf.transform(doc(pd.concat([old.tail(200000), cur]))))
        allv /= np.linalg.norm(allv, axis=1, keepdims=True) + 1e-9
        ids = pd.concat([old.tail(200000), cur]).post_id.to_numpy()
        V = dict(zip(ids, allv.astype(np.float32)))
        # 1) fit p(u comments on s) on the previous month, with profiles built before it
        idx1, U1, a1, H1 = profiles(C, V, t_1)
        sp = p[(p.month == prev) & p.post_id.isin(V.keys())]
        pos = C[(C.created_at_i >= t_1) & (C.created_at_i < t0) & C.person.isin(idx1) & C.story_id.isin(sp.post_id)]
        pos = pos.drop_duplicates(["person", "story_id"])
        rng = np.random.default_rng(0)
        pu, ps = pos.person.map(idx1).to_numpy(), pos.story_id.to_numpy()
        nu = rng.integers(0, len(idx1), len(pos) * NEG)
        ns = rng.choice(sp.post_id.to_numpy(), len(pos) * NEG)
        hour = dict(zip(sp.post_id, (sp.created_at_i // 3600) % 24))
        def X_of(u, s):
            Sv = np.stack([V[x] for x in s])
            return pair_x((U1[u] * Sv).sum(1), a1[u], H1[u, np.array([hour[x] for x in s], dtype=int)])
        Xp, Xn = X_of(pu, ps), X_of(nu, ns)
        lr = LogisticRegression(max_iter=500).fit(np.vstack([Xp, Xn]), np.r_[np.ones(len(Xp)), np.zeros(len(Xn))])
        # intercept: negatives were sampled at NEG per positive out of all (people x stories) pairs
        base = len(pos) / (len(idx1) * len(sp))
        corr = np.log(base / (1 - base)) - np.log(1 / NEG)
        # 2) apply to month m with profiles built before m
        idx, U, a, H = profiles(C, V, t0)
        sm = p[p.month == m]
        Sv = np.stack([V[x] for x in sm.post_id])
        hrs = ((sm.created_at_i // 3600) % 24).to_numpy().astype(int)
        w, b = lr.coef_[0], lr.intercept_[0] + corr
        tally, reg = np.zeros(len(sm)), np.zeros(len(sm))
        heavy = a >= np.quantile(a, 0.95)
        for i in range(0, len(sm), 2000):
            aff = U @ Sv[i:i + 2000].T                                   # people x stories
            z = (w[0] * aff + w[1] * np.log1p(a)[:, None] + w[2] * 24 * H[:, hrs[i:i + 2000]]
                 + w[3] * aff * np.log1p(a)[:, None] + b)
            pr = 1 / (1 + np.exp(-z))
            tally[i:i + 2000] = pr.sum(0)
            reg[i:i + 2000] = (pr[heavy] > 0.02).sum(0)
        out.append(pd.DataFrame({"post_id": sm.post_id.to_numpy(), "crowd_tally": tally, "crowd_regulars": reg}))
        hit = pd.Series(tally, index=sm.post_id).corr(np.log1p(sm.set_index("post_id").points), method="spearman")
        print(m, f"people {len(idx)} pairs {len(pos)} coef {np.round(w, 2)} spearman(tally, points) {hit:.3f}",
              flush=True)
    D = pd.concat(out, ignore_index=True)
    D.to_parquet(os.path.join(S.LOCAL, "crowd_features.parquet"), index=False)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
