"""18:00 round 2 (cached v4 table, fully fetched days, hybrid model): title similarity to earlier daily top-30 hits
(TF-IDF cosine: nearest and mean of the 5 nearest, earlier days only), training re-weighted toward stories still
rising at T, and recall among stories already posted / back on the page at T.

    python v4_t18b.py [split=2026-09-01] [times=t18]
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

import daily_v4 as V
import top100 as H
import v4_t18 as X

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
TS = (sys.argv[2] if len(sys.argv) > 2 else "t18").split(",")
rng = np.random.default_rng(0)
C = X.C.copy()
P = H.stories().set_index("post_id")
title = C.post_id.map(P.title).fillna("")

# title similarity to earlier hits: daily top 30 of the 60 days before D (lists from frontday*.jsonl)
L = pd.concat([pd.read_json(os.path.join(H.CACHE, f), lines=True, dtype={"day": str})
               for f in ("frontday.jsonl", "frontday_old.jsonl")]).drop_duplicates(["day", "post_id"])
L = L[L["rank"] <= 30]
L["title"] = L.post_id.map(P.title).fillna("")
vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True).fit(L[L.day < SPLIT].title)
sim_max, sim_top5 = np.zeros(len(C)), np.zeros(len(C))
for d, idx in C.groupby("day").indices.items():
    past = L[(L.day < d) & (L.day >= (pd.Timestamp(d) - pd.Timedelta(days=60)).strftime("%Y-%m-%d"))]
    S = (vec.transform(title.iloc[idx]) @ vec.transform(past.title).T).toarray()
    S.sort(1)
    sim_max[idx], sim_top5[idx] = S[:, -1], S[:, -5:].mean(1)
C["title_sim_max"], C["title_sim_top5"] = sim_max, sim_top5


def per_day(te, s):
    te = te.assign(s=np.where(te.on_earlier_list == 1, -1e9, s))
    return pd.Series({d: len(set(g[g.real_rank <= 30].post_id) & set(g.nlargest(30, "s").post_id)) / 30 for d, g in te.groupby("day")})


def hyb(tr, te, cols, w=None):
    clf = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=15, min_child_samples=10, subsample=0.8,
                             subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
    clf.fit(tr[cols], tr.real_rank <= 30, sample_weight=w)
    return V.hybrid(te.day, clf.predict_proba(te[cols])[:, 1], V.fit_rank(tr, cols).predict(te[cols]))


def vs(a, b):
    d = (b - a).to_numpy()
    boot = [rng.choice(d, len(d)).mean() for _ in range(2000)]
    return f"{b.mean():.3f} ({d.mean():+.3f} [{np.percentile(boot, 2.5):+.3f}, {np.percentile(boot, 97.5):+.3f}])"


for t in TS:
    D = C[C[f"{t}_visible"] == 1]
    tr, te = D[D.day < SPLIT], D[D.day >= SPLIT]
    base = ["on_earlier_list", "text_score"] + [f"{t}_{c}" for c in list(V.VC) + ["stage1", "c_all", "c_last3h"]]
    a = per_day(te, hyb(tr, te, base))
    vis = te.groupby("day").apply(lambda g: (g.real_rank <= 30).sum() / 30)
    print(f"{t}: hybrid {a.mean():.3f} of the real top 30; already posted / back on the page at {t}: {vis.mean():.3f}; "
          f"recall among those: {(a * 30 / (vis * 30)).mean():.3f}", flush=True)
    rising = ((tr[f"{t}_gain60"] > 0) | (tr[f"{t}_assigned"] == 0)).to_numpy()
    runs = {
        "+ title similarity to past hits": lambda: per_day(te, hyb(tr, te, base + ["title_sim_max", "title_sim_top5"])),
        "train weight x2 on stories still rising": lambda: per_day(te, hyb(tr, te, base, np.where(rising, 2.0, 1.0))),
        "train weight x2 on young stories (<6 h)": lambda: per_day(te, hyb(tr, te, base, np.where(tr[f"{t}_age_h"] < 6, 2.0, 1.0))),
    }
    for name, f in runs.items():
        print(f"  {name:42s}", vs(a, f()), flush=True)
