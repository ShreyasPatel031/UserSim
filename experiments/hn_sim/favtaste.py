"""Favorites taste block for the top-100 scoreboard (favs.py -> <cache>/hn_favs.jsonl).

HN favorites are the closest public thing to a person's upvotes, but they are undated. For each month M only
favorited stories POSTED before M count (a favorite must come after its story, so this never uses a story from M or
later). Per month M:
  people   everyone with 5+ such favorites
  taste    mean title vector (TF-IDF + SVD, 128 dims) of the stories they favorited; favorite count
  domain   how many favorites (and favoriting people) each domain collected
Per story in M:
  fav_tally        sum over people of log1p(favorites) * max(affinity, 0)^3      expected 'likes' from these people
  fav_fans         people whose taste is close (affinity > 0.5)
  fav_dom_favs / fav_dom_people   the story's domain's favorite record
  fav_early_*      early commenters (first 60 min) who are favoriters: count, their affinity sum / max
The vectorizer is fit once on 2023-2024 titles (unsupervised; no outcomes). -> <cache>/f_favtaste.parquet

    python favtaste.py
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from urllib.parse import urlparse

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

import store as S
import top100 as H

DIM = 128
MIN_FAVS = 5


def main() -> None:
    p = H.stories()
    favs = defaultdict(set)
    for line in open(os.path.join(S.LOCAL, "hn_favs.jsonl")):
        r = json.loads(line)
        favs[r["person"]].update(r["story_ids"])
    print("people with favorites fetched", len(favs), "favorites", sum(map(len, favs.values())), flush=True)
    host = p.url.fillna("").map(lambda u: urlparse(u).netloc.lower().removeprefix("www."))
    doc = p.title.fillna("") + " " + host
    fit = (p.day < "2025-01-01").to_numpy()
    tf = TfidfVectorizer(min_df=5, ngram_range=(1, 2), sublinear_tf=True, max_features=200000)
    X = tf.fit_transform(doc[fit])
    svd = TruncatedSVD(DIM, random_state=0).fit(X[-300000:])
    V = np.zeros((len(p), DIM), np.float32)
    for i in range(0, len(p), 200000):
        v = svd.transform(tf.transform(doc.iloc[i:i + 200000]))
        V[i:i + 200000] = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
    row = pd.Series(np.arange(len(p)), index=p.post_id)
    t_of = p.created_at_i.to_numpy()
    # favorites as (person, row) pairs for stories we have
    pairs = [(u, row[s]) for u, ss in favs.items() for s in ss if s in row.index]
    F = pd.DataFrame(pairs, columns=["person", "row"])
    F["t"] = t_of[F.row.to_numpy()]
    F["host"] = host.to_numpy()[F.row.to_numpy()]
    print("favorites on stories since 2023:", len(F), flush=True)

    c = H.comments()[["person", "story_id", "created_at_i"]]
    c = c[c.story_id.isin(row.index)]
    age = c.created_at_i.to_numpy() - t_of[row[c.story_id].to_numpy()]
    early = c[(age >= 0) & (age <= 3600)].drop_duplicates(["person", "story_id"])
    early = early[early.person.isin(favs.keys())]

    out = []
    months = sorted(m for m in p.month.unique() if m >= "2023-03")
    for m in months:
        t0 = H.month_t0(m)
        f = F[F.t < t0]
        cnt = f.person.value_counts()
        people = cnt[cnt >= MIN_FAVS].index
        idx = {u: i for i, u in enumerate(people)}
        cur = np.flatnonzero((p.month == m).to_numpy())
        res = pd.DataFrame({"post_id": p.post_id.to_numpy()[cur]})
        if len(people):
            ff = f[f.person.isin(idx)]
            U = np.zeros((len(people), DIM), np.float32)
            np.add.at(U, ff.person.map(idx).to_numpy(), V[ff.row.to_numpy()])
            U /= np.linalg.norm(U, axis=1, keepdims=True) + 1e-9
            w = np.log1p(cnt[people].to_numpy()).astype(np.float32)
            Sv = V[cur]
            tally, fans = np.zeros(len(cur)), np.zeros(len(cur))
            for i in range(0, len(cur), 4000):
                aff = U @ Sv[i:i + 4000].T
                tally[i:i + 4000] = (w[:, None] * np.clip(aff, 0, None) ** 3).sum(0)
                fans[i:i + 4000] = (aff > 0.5).sum(0)
            res["fav_tally"], res["fav_fans"] = tally, fans
            dom = f.groupby("host").agg(n=("person", "size"), u=("person", "nunique"))
            h = host.to_numpy()[cur]
            res["fav_dom_favs"] = pd.Series(h).map(dom.n).fillna(0).to_numpy()
            res["fav_dom_people"] = pd.Series(h).map(dom.u).fillna(0).to_numpy()
            res.loc[h == "", ["fav_dom_favs", "fav_dom_people"]] = 0
            e = early[early.story_id.isin(res.post_id) & early.person.isin(idx)]
            if len(e):
                ea = (U[e.person.map(idx).to_numpy()] * V[row[e.story_id].to_numpy()]).sum(1)
                g = pd.DataFrame({"story_id": e.story_id.to_numpy(), "a": ea}).groupby("story_id").a
                res["fav_early_n"] = res.post_id.map(g.size()).fillna(0).to_numpy()
                res["fav_early_aff_sum"] = res.post_id.map(g.sum()).fillna(0).to_numpy()
                res["fav_early_aff_max"] = res.post_id.map(g.max()).fillna(0).to_numpy()
        out.append(res)
        print(m, "people", len(people), flush=True)
    B = pd.concat(out, ignore_index=True)
    B = B.set_index("post_id").reindex(p.post_id).fillna(0).reset_index()
    B.to_parquet(os.path.join(S.LOCAL, "f_favtaste.parquet"), index=False)
    print("favtaste block", B.shape, flush=True)


if __name__ == "__main__":
    main()
