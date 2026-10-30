"""Our model + early upvotes (Quality News minute data), trained combination.

Stage 1: our scoreboard model (post + early comments / who at 30 & 60 min + submitter), trained on months before
2026-08, scores every story of Aug-Sep 2026 (out of sample for all of them).
Stage 2: a small model on [stage-1 score, upvotes at 15/30/60 min, expected upvotes, best top-page rank], trained on
Quality News days before SPLIT, tested on days from SPLIT (top 100 by points: daily top-k recall).
Stories Quality News did not keep (404: ended with ~1-3 points) get upvotes 1 and rank 91 (not on the page).

    python qn_eval.py [split=2026-09-16]
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
q = pd.read_json(os.path.join(H.CACHE, "qn_early.jsonl"), lines=True).drop_duplicates("post_id")
q = q[q.status.isin([200, 404])]
p = H.stories()
p = p[(p.month >= "2023-03") & (p.month <= "2026-09")].reset_index(drop=True)
y = np.log1p(p.points.to_numpy())
rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
base = ["post", "early30", "who30", "early60", "who60", "submitter"]
X = pd.concat([pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
               .set_index("post_id").reindex(p.post_id).reset_index(drop=True) for b in base], axis=1)
tr, te = (p.month < "2026-08").to_numpy(), (p.month >= "2026-08").to_numpy()
oof, txt = T.text_scores(p, y, tr, te)
keep = (rk <= 100) | (np.random.default_rng(0).random(len(p)) < 0.25)
c1 = lgb.LGBMClassifier(**{**H.GBM, "scale_pos_weight": 2}).fit(X[tr].assign(text_score=oof)[keep[tr]], (rk[tr & keep] <= 100).astype(int))
D = p[te][["post_id", "day", "points"]].assign(stage1=c1.predict_proba(X[te].assign(text_score=txt))[:, 1], rk=rk[te],
                                                y=y[te]).merge(q, on="post_id", how="inner")
for a in (15, 30, 60):
    D[f"qn_up{a}"] = D[f"qn_up{a}"].fillna(1)
    D[f"qn_exp{a}"] = D[f"qn_exp{a}"].fillna(D[f"qn_exp{a}"].median())
    D[f"qn_toprank{a}"] = D[f"qn_toprank{a}"].fillna(91)
n = D.groupby("day").size()
D = D[D.day.isin(n[n >= 500].index)]          # only fully fetched days
qcols = [f"qn_{k}{a}" for k in ("up", "exp", "toprank") for a in (15, 30, 60)]
trd, ted = D[D.day < SPLIT], D[D.day >= SPLIT]
print("QN days: train", trd.day.nunique(), "test", ted.day.nunique(), flush=True)
c2 = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8,
                        subsample_freq=1, verbose=-1, random_state=0)
c2.fit(trd[["stage1"] + qcols], (trd.rk <= 100).astype(int))
ted = ted.assign(stage2=c2.predict_proba(ted[["stage1"] + qcols])[:, 1], sh60=np.log1p(ted.qn_up60))
c3 = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8,
                        subsample_freq=1, verbose=-1, random_state=0).fit(trd[qcols], (trd.rk <= 100).astype(int))
ted = ted.assign(qn_only=c3.predict_proba(ted[qcols])[:, 1])
rng = np.random.default_rng(0)
rows = []
for col, name in (("stage1", "ours 60 min"), ("sh60", "Szabo-Huberman: upvotes at 60 min"),
                  ("qn_only", "early upvotes + rank model"), ("stage2", "ours 60 min + early upvotes (trained)")):
    r = {k: R.boot(T.day_hits(ted.assign(s=ted[col]), "s", k, rng)) for k in (100, 30, 10)}
    print(name, json.dumps(r), flush=True)
    rows += [{"kind": "qn_eval", "variant": name, "k": k, "recall": v[0], "lo": v[1], "hi": v[2],
              "test_days": int(ted.day.nunique()), "made_on": S.now()} for k, v in r.items()]
S.write("hn_scores", pd.DataFrame(rows))
