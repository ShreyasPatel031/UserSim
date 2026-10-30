"""Prior work vs our model, same held-out days, same metrics.

Methods
  ours_post         our post-only model (top100 'post' block, classifier on the day's top 100)
  dubach            Philipp Dubach's RoBERTa title model alone (dubach.py)
  ours_post+dubach  his score as an extra feature
  szabo_huberman    Szabo & Huberman (2010): rank by log early upvotes (Quality News, 30 / 60 min)
  ours_60           our best: post + early comments + who (30 / 60 min)
  ours_60+qn        plus Quality News early upvotes and top-page rank (15 / 30 / 60 min)
Metrics: recall@100/30/10 per day; AUC for >=100 points (Dubach's target); balanced front-page accuracy (Taylor's:
top-100 vs an equal random sample of the rest, predicted front page = top half by score).
Every model variant in a comparison trains on the same window (TRAIN_FROM .. month before the test month), so the
only difference is the feature.

    python prior_eval.py dubach      # test 2026-05..09, train from 2026-03 (after Dubach's training data)
    python prior_eval.py qn          # test 2026-09, train 2026-06..08 (Quality News coverage fetched)
"""
from __future__ import annotations

import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import rank as R
import store as S
import top10 as T
import top100 as H


def balanced_acc(P: pd.DataFrame, col: str, rng) -> float:
    acc = []
    for _, g in P.groupby("day"):
        pos = g[g.rk <= 100]
        neg = g[g.rk > 100]
        if len(pos) < 50 or len(neg) < len(pos):
            continue
        b = pd.concat([pos, neg.sample(len(pos), random_state=int(rng.integers(1e9)))])
        pred = b[col].rank(method="first", ascending=False) <= len(b) / 2
        acc.append(float((pred == (b.rk <= 100)).mean()))
    return round(float(np.mean(acc)), 3)


def evaluate(P: pd.DataFrame, cols: list[str], tag: str) -> list[dict]:
    rng = np.random.default_rng(0)
    rows = []
    for c in cols:
        r = {k: R.boot(T.day_hits(P.assign(s=P[c]), "s", k, rng)) for k in (100, 30, 10)}
        auc = round(float(roc_auc_score(P.points >= 100, P[c].fillna(P[c].min()))), 3)
        ba = balanced_acc(P, c, rng)
        print(f"{tag} {c}: recall {json.dumps(r)}  AUC(>=100) {auc}  balanced-acc {ba}", flush=True)
        rows += [{"kind": "prior_work", "comparison": tag, "method": c, "k": k, "recall": v[0], "lo": v[1], "hi": v[2],
                  "auc100": auc, "balanced_acc": ba, "made_on": S.now()} for k, v in r.items()]
    return rows


def run(test: list[str], train_from: str, extra: pd.DataFrame, variants: dict, tag: str) -> None:
    p = H.stories()
    p = p[(p.month >= train_from) & (p.month <= test[-1])].reset_index(drop=True)
    y = np.log1p(p.points.to_numpy())
    rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
    blk = {}
    for b in {x for cols, _ in variants.values() for x in cols if x in H.BLOCK_FILES}:
        f = pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
        blk[b] = f.set_index("post_id").reindex(p.post_id).reset_index(drop=True)
    ex = extra.drop_duplicates("post_id").set_index("post_id").reindex(p.post_id).reset_index(drop=True)
    out = []
    for m in test:
        tr, te = (p.month < m).to_numpy(), (p.month == m).to_numpy()
        oof, txt = T.text_scores(p, y, tr, te)
        res = {"day": p.day[te].to_numpy(), "y": y[te], "points": p.points[te].to_numpy(), "rk": rk[te]}
        for name, (cols, raw) in variants.items():
            if raw:                                    # a score used as is (no training)
                res[name] = ex.loc[te, raw].to_numpy()
                continue
            X = pd.concat([blk[b] for b in cols if b in blk] + [ex[[c for c in cols if c in ex]]], axis=1)
            c = lgb.LGBMClassifier(**{**H.GBM, "scale_pos_weight": 2})
            c.fit(X[tr].assign(text_score=oof), (rk[tr] <= 100).astype(int))
            res[name] = c.predict_proba(X[te].assign(text_score=txt))[:, 1]
        out.append(pd.DataFrame(res))
        print("month", m, flush=True)
    P = pd.concat(out, ignore_index=True)
    S.write("hn_scores", pd.DataFrame(evaluate(P, list(variants), tag)))


if __name__ == "__main__":
    if sys.argv[1] == "dubach":
        d = pd.read_parquet(os.path.join(H.CACHE, "dubach.parquet"))
        run(["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"], "2026-03", d, {
            "ours_post": (["post"], None), "dubach": ([], "dubach"), "ours_post+dubach": (["post", "dubach"], None),
            "ours_60": (["post", "early30", "who30", "early60", "who60"], None),
            "ours_60+dubach": (["post", "early30", "who30", "early60", "who60", "dubach"], None)}, "dubach")
    elif sys.argv[1] == "qn":
        q = pd.read_json(os.path.join(H.CACHE, "qn_early.jsonl"), lines=True)
        q = q[q.status.isin([200, 404])].copy()
        for a in (15, 30, 60):        # not kept by Quality News (404) = ended with ~1-3 points: early upvotes ~1
            q[f"qn_up{a}"] = q[f"qn_up{a}"].fillna(1)
            q[f"qn_toprank{a}"] = q[f"qn_toprank{a}"].fillna(91)
        q["sh30"], q["sh60"] = np.log1p(q.qn_up30), np.log1p(q.qn_up60)
        qc = ["qn_up15", "qn_up30", "qn_up60", "qn_toprank15", "qn_toprank30", "qn_toprank60"]
        months = sorted(pd.to_datetime(H.stories().set_index("post_id").created_at_i.reindex(q.post_id), unit="s")
                        .dt.strftime("%Y-%m").dropna().unique())
        print("Quality News months fetched:", months, flush=True)
        test = [months[-1]]
        run(test, months[0], q, {
            "szabo_huberman_30": ([], "sh30"), "szabo_huberman_60": ([], "sh60"),
            "ours_post": (["post"], None), "ours_post+qn30": (["post", "qn_up15", "qn_up30", "qn_toprank15", "qn_toprank30"], None),
            "ours_60": (["post", "early30", "who30", "early60", "who60"], None),
            "ours_60+qn": (["post", "early30", "who30", "early60", "who60"] + qc, None)}, "qn")
