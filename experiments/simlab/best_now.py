"""Full-holdout run of tonight's winners together: popularity + relationships + simple taste + personas v1-v4
+ collaborative filtering on teams (phase2) + person x launch embedding interactions; with and without follows.
-> simlab/reports/best_now.json"""
import json, os
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.decomposition import PCA
from . import store, choice
from .phase2 import cf_features
from .path90 import load
from .persona import CACHE

HERE = os.path.dirname(os.path.abspath(__file__))


def tt_features(D, I, E):
    Z = np.load(f"{store.RAW}/emb.npz"); li = {x: k for k, x in enumerate(Z["launch_ids"])}; EM = Z["launch"]
    Es = E[E.item.isin(li)].sort_values("date")
    hist = Es.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    pv = {}
    for g in D.g.unique():
        u, d = g.split("|"); h = [li[i] for dt, i in hist.get(u, []) if dt < d]
        pv[g] = EM[h].mean(0) if h else np.zeros(EM.shape[1], np.float32)
    X = np.stack([pv[g] for g in D.g]) * np.stack([EM[li[i]] if i in li else np.zeros(EM.shape[1]) for i in D.id])
    Xp = PCA(16, random_state=0).fit(X[(D.day < "2026-10-01").values][:200000]).transform(X)
    for j in range(16):
        D[f"tt{j}"] = Xp[:, j]
    return D


def main():
    P, I, E = store.load(); D = choice.rows()
    for k, f in {"p1": "taste_ratings.jsonl", "p2": "taste_v2_ratings.jsonl", "p3": "taste_v3_ratings.jsonl", "p4": "taste_best4_full.jsonl"}.items():
        R = load(f"{CACHE}/{f}"); D[k] = [R.get(g, {}).get(i, np.nan) for g, i in zip(D.g, D.id)]; D[k] = D.groupby("g")[k].rank(pct=True)
    D = D.dropna(subset=["p1", "p2", "p3", "p4"])
    D = cf_features(D, P, I, E); D = tt_features(D, I, E)
    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"]
    base = ["pop", "backed", "topic", "meaning"]; pers = ["p1", "p2", "p3", "p4"]; cf = ["cf_team", "nbr_team", "nbr_pop"]; tt = [f"tt{j}" for j in range(16)]
    res = []
    for fol in (False, True):
        F = ["follow"] if fol else []
        for nm, c in [("base", base), ("+personas", base + pers), ("+personas+cf", base + pers + cf), ("+personas+cf+two-tower", base + pers + cf + tt)]:
            p = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.04, num_leaves=15, min_child_samples=50, verbose=-1).fit(tr[c + F], tr.y).predict_proba(te[c + F])[:, 1]
            h, a = choice.person_metrics(te, p)
            res.append({"follows": fol, "model": nm, "top3_hit": round(h, 3), "auc": round(a, 3)}); print(res[-1], flush=True)
    json.dump(res, open(f"{HERE}/reports/best_now.json", "w"), indent=1)


if __name__ == "__main__":
    main()
