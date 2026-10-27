"""Phase 2 candidates on the person holdout (Sep train, Oct test), scored with the same metrics as choice.py.
New signals (all from events before 2026-09-01, so leak-free for both train and test months):
  cf_team    low-rank match between the person and the launch's team (SVD of the person x maker/poster backing matrix)
  nbr_team   share of the person's 50 most similar backers who backed this team before (neighbour collaborative filtering)
  nbr_pop    the same neighbours' backing of the team, weighted by how much they back anyone (crowd within your circle)
Models: GBM classifier vs LambdaRank (grouped by person-day), with and without the undated follow lists.
usage: python -m simlab.phase2 -> simlab/reports/phase2_candidates.json"""
import json, os
from collections import defaultdict
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from . import store, choice
from .path90 import load
from .persona import CACHE

HERE = os.path.dirname(os.path.abspath(__file__))
CUT = "2026-09-01"


def cf_features(D, P, I, E):
    team = {r.id: set(json.loads(r.makers)) | {r.poster} for r in I.itertuples()}
    ev = E[(E.date < CUT) & E.item.isin(team)]
    people = sorted(set(ev.person) | set(D.person)); pix = {u: k for k, u in enumerate(people)}
    members = sorted({m for t in team.values() for m in t if m}); mix = {m: k for k, m in enumerate(members)}
    rows, cols = [], []
    for u, it in zip(ev.person, ev.item):
        for m in team[it]:
            if m in mix:
                rows.append(pix[u]); cols.append(mix[m])
    M = sparse.csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(len(people), len(members)))
    M.data = np.log1p(M.data)
    svd = TruncatedSVD(32, random_state=0); U = svd.fit_transform(M); V = svd.components_.T
    Un = U / (np.linalg.norm(U, axis=1, keepdims=True) + 1e-9)
    # neighbours: cosine in the latent space among people who backed anyone
    active = np.where(np.asarray(M.sum(1)).ravel() > 0)[0]
    nbrs = {}
    for start in range(0, len(people), 2000):
        blk = Un[start:start + 2000] @ Un[active].T
        top = np.argsort(-blk, axis=1)[:, 1:51]
        for j, row in enumerate(top):
            nbrs[start + j] = active[row]
    Mb = (M > 0).astype(np.float32).tocsr()
    nbv = {}  # per person: how many of their 50 neighbours backed each team member (computed once per person)
    for u in set(D.person):
        i = pix[u]; nb = nbrs.get(i)
        nbv[u] = np.asarray(Mb[nb].sum(0)).ravel() if nb is not None and len(nb) else None
    cf, nt, npop = [], [], []
    for u, it in zip(D.person, D.id):
        i = pix[u]; t = [mix[m] for m in team.get(it, ()) if m in mix]
        cf.append(float(max((U[i] @ V[c] for c in t), default=0.0)))
        v = nbv.get(u)
        if t and v is not None:
            nt.append(float(v[t].max() / 50)); npop.append(float(v[t].sum()))
        else:
            nt.append(0.0); npop.append(0.0)
    D["cf_team"], D["nbr_team"], D["nbr_pop"] = cf, nt, np.log1p(npop)
    for c in ("cf_team", "nbr_team", "nbr_pop"):
        D[c] = D.groupby("g")[c].rank(pct=True)
    return D


def main():
    P, I, E = store.load()
    D = choice.rows()
    files = {"p1": "taste_ratings.jsonl", "p2": "taste_v2_ratings.jsonl", "p3": "taste_v3_ratings.jsonl", "p4": "taste_best4_full.jsonl"}
    for k, f in files.items():
        R = load(f"{CACHE}/{f}"); D[k] = [R.get(g, {}).get(i, np.nan) for g, i in zip(D.g, D.id)]
        D[k] = D.groupby("g")[k].rank(pct=True)
    D = D.dropna(subset=list(files))
    D = cf_features(D, P, I, E)
    tr, te = D[D.day < "2026-10-01"].sort_values("g"), D[D.day >= "2026-10-01"]
    base = ["pop", "backed", "topic", "meaning"]; pers = ["p1", "p2", "p3", "p4"]; cfc = ["cf_team", "nbr_team", "nbr_pop"]
    P_ = dict(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1)

    def clf(c):
        return lgb.LGBMClassifier(**P_).fit(tr[c], tr.y).predict_proba(te[c])[:, 1]

    def rank(c):
        g = tr.groupby("g", sort=False).size().loc[tr.g.unique()].values
        return lgb.LGBMRanker(**P_).fit(tr[c], tr.y, group=g).predict(te[c])
    res = []
    for fol in (False, True):
        F = ["follow"] if fol else []
        for name, c in [("base", base), ("base+persona", base + pers), ("base+cf", base + cfc), ("base+persona+cf", base + pers + cfc)]:
            for mname, fn in (("trees", clf), ("ranker", rank)):
                hit, auc = choice.person_metrics(te, fn(c + F))
                res.append({"follows": fol, "features": name, "model": mname, "top3_hit": round(hit, 3), "auc": round(auc, 3)})
                print(res[-1], flush=True)
    os.makedirs(f"{HERE}/reports", exist_ok=True)
    json.dump(res, open(f"{HERE}/reports/phase2_candidates.json", "w"), indent=1)


if __name__ == "__main__":
    main()
