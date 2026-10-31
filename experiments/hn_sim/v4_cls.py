"""Top-30 membership classifiers vs the lambdarank ranker, per forecast time (cached v4 table, fully fetched days).
Hybrid: the classifier picks the 30, the ranker orders them (so the top 10 keeps the ranker's quality).

    python v4_cls.py [split=2026-09-01] [times=t18,t21,eod]
"""
import json
import sys

import lightgbm as lgb
import numpy as np

import daily_v4 as V
import v4_t18 as X

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
TS = (sys.argv[2] if len(sys.argv) > 2 else "t18,t21,eod").split(",")


def cls(tr, cols, n=400, leaves=15, seed=0, lr=0.05):
    return lgb.LGBMClassifier(n_estimators=n, learning_rate=lr, num_leaves=leaves, min_child_samples=10, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=seed).fit(tr[cols], tr.real_rank <= 30)


def hybrid(te, p_in, s_rank):
    """Classifier picks the top 30 per day; the ranker orders those 30 (others keep classifier order below)."""
    te = te.assign(p=p_in, r=s_rank)
    te["in30"] = te.groupby("day").p.rank(ascending=False) <= 30
    return np.where(te.in30, 1e6 + te.r, te.p)


for t in TS:
    D = X.C[X.C[f"{t}_visible"] == 1]
    tr, te = D[D.day < SPLIT], D[D.day >= SPLIT]
    base = ["on_earlier_list", "text_score"] + [f"{t}_{c}" for c in list(V.VC) + ["stage1", "c_all", "c_last3h"]]
    allc = base + X.WHO + X.EARLY
    rk = X.fit(tr, base).predict(te[base])
    p1 = cls(tr, base).predict_proba(te[base])[:, 1]
    runs = {
        "ranker (current)": rk,
        "classifier": p1,
        "classifier + history": cls(tr, allc).predict_proba(te[allc])[:, 1],
        "classifier, 800 trees lr .025": cls(tr, base, 800, 15, 0, 0.025).predict_proba(te[base])[:, 1],
        "classifier, 5 seeds": np.mean([cls(tr, base, seed=s).predict_proba(te[base])[:, 1] for s in range(5)], 0),
        "hybrid: classifier picks, ranker orders": hybrid(te, p1, rk),
    }
    print(t, flush=True)
    for name, s in runs.items():
        print(f"  {name:40s}", json.dumps(X.sc(te, s)), flush=True)
