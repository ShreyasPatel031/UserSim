"""Screening-sample evaluation of everything tonight: base factors, collaborative filtering (phase2), new relationship
signals (rel.py), and persona cards (variants.py configs), with and without the undated follow lists.
Same Sep-train / Oct-test split; trees (GBM) on person x launch rows. -> simlab/reports/screen.json"""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
from . import store, choice, rel
from .phase2 import cf_features
from .variants import sample
from .persona import CACHE

HERE = os.path.dirname(os.path.abspath(__file__))
PERSONAS = ["v1", "c", "c+r+b", "c+li", "c+act", "rich", "c_ret"]


def main():
    P, I, E = store.load()
    S = {u + "|" + d for u, d in sample()}
    D = choice.rows(); D = D[D.g.isin(S)].copy()
    for k in PERSONAS:
        R = {}
        p = f"{CACHE}/variant_{k}.jsonl"
        if os.path.exists(p):
            for l in open(p):
                r = json.loads(l); R[r["person"] + "|" + r["day"]] = r["ratings"]
        D[k] = [R.get(g, {}).get(i, np.nan) for g, i in zip(D.g, D.id)]
        D[k] = D.groupby("g")[k].rank(pct=True)
    D = D.dropna(subset=PERSONAS)
    D = cf_features(D, P, I, E)
    D = rel.features(D)
    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"]
    base = ["pop", "backed", "topic", "meaning"]; cf = ["cf_team", "nbr_team", "nbr_pop"]
    relc = ["hunted_team", "x_mentions_team"]; rel_undated = ["followed_by_team"]

    def run(c):
        p = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=7, min_child_samples=40, verbose=-1).fit(tr[c], tr.y).predict_proba(te[c])[:, 1]
        h, a = choice.person_metrics(te, p)
        return round(h, 3), round(a, 3)
    res = []
    for fol in (False, True):
        F = ["follow"] + rel_undated if fol else []
        for name, c in [("base", base), ("base+cf", base + cf), ("base+cf+rel", base + cf + relc)] + \
                       [(f"base+cf+rel+{k}", base + cf + relc + [k]) for k in PERSONAS] + \
                       [("base+cf+rel+all personas", base + cf + relc + PERSONAS)]:
            h, a = run(c + F)
            res.append({"undated_follows": fol, "model": name, "top3_hit": h, "auc": a}); print(res[-1], flush=True)
    print("test person-days", te.g.nunique(), "| share with new signals:", {c: round(float((te.groupby("g")[c].max() > 0).mean()), 3) for c in relc + rel_undated})
    json.dump(res, open(f"{HERE}/reports/screen.json", "w"), indent=1)


if __name__ == "__main__":
    main()
