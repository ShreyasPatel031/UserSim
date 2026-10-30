"""People react differently to the same page, learned jointly (attribute-aware factorization, as in cold-start
recommenders): score(person, launch) = linear(person-model inputs + page inputs) + e_person . (W @ page_traits)
e_person: a learned 16-number taste vector per person; W maps every page input (ps_/pf_/vs_) into the same space, so
people with few picks borrow from similar people. Trained on the previous month with a listwise loss over each
person-day line-up (the real picks vs the rest), tested on the next month (people unseen in training get e = 0).
Compared with the LightGBM person+page model on the same rows, and blended (average within-person-day rank).
usage: python -m simlab.page_mf [workers] -> reports/page_mf.json"""
import json, os, sys
os.environ.setdefault("OMP_NUM_THREADS", "2")
import multiprocessing as mp
import numpy as np, pandas as pd, lightgbm as lgb, torch
from sklearn.metrics import roc_auc_score
from . import choice, popscore as PS
from .page_taste import traits

HERE = os.path.dirname(os.path.abspath(__file__))
MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
K = 16


def tensors(D, Z, feats, people, mu, sd):
    zi = {x: k for k, x in enumerate(Z.index)}
    A = np.stack([Z.values[zi[x]] if x in zi else np.zeros(Z.shape[1], np.float32) for x in D.id])
    X = ((D[feats].values - mu) / sd).astype(np.float32); X = np.nan_to_num(X)
    pid = np.array([people.get(u, -1) for u in D.person])
    grp = (D.person + "|" + D.day).astype("category").cat.codes.values
    return torch.tensor(X), torch.tensor(A, dtype=torch.float32), torch.tensor(pid), torch.tensor(grp, dtype=torch.long), torch.tensor(D.y.values, dtype=torch.float32)


class Model(torch.nn.Module):
    def __init__(self, nf, na, npeople):
        super().__init__()
        self.lin = torch.nn.Linear(nf + na, 1)
        self.E = torch.nn.Embedding(npeople + 1, K); torch.nn.init.normal_(self.E.weight, 0, 0.01)
        self.W = torch.nn.Linear(na, K, bias=False)

    def forward(self, X, A, pid):
        e = self.E(torch.where(pid < 0, torch.full_like(pid, self.E.num_embeddings - 1), pid))
        e = e * (pid >= 0).float().unsqueeze(1)                       # unseen people: no personal taste
        return self.lin(torch.cat([X, A], 1)).squeeze(1) + (e * self.W(A)).sum(1)


def listwise(s, grp, y, ngrp):
    """-sum over person-days of log softmax of the real picks against the day's line-up."""
    m = torch.zeros(ngrp).index_reduce_(0, grp, s, "amax", include_self=False)
    z = torch.zeros(ngrp).index_add_(0, grp, torch.exp(s - m[grp]))
    lse = torch.log(z) + m
    return -((s - lse[grp]) * y).sum() / y.sum()


def month(m):
    torch.set_num_threads(2)
    prev = PS.month_start(m, 1); cf = PS.fit_cf(prev); rng = np.random.default_rng(0)

    def sample(D, n):
        keep = set()
        for d, g in D.groupby("day"):
            keep |= {u + "|" + d for u in rng.permutation(g.person.unique())[:n]}
        return D[(D.person + "|" + D.day).isin(keep)].copy()
    tr = sample(choice.rows(day_from=prev, day_to=PS.month_end(prev[:7])), 400)
    te = sample(choice.rows(day_from=m + "-01", day_to=PS.month_end(m)), 200)
    tr, te = PS.featurize(tr, cf, prev), PS.featurize(te, cf, prev)
    Z, _ = traits()
    for D in (tr, te):
        D["id"] = D.id.astype(str)
    tr = tr.join(Z, on="id", rsuffix="_z"); te = te.join(Z, on="id", rsuffix="_z")
    pc = list(Z.columns); feats = PS.FEATS
    # LightGBM person + page on the same rows (the bar to beat)
    gb = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=50, colsample_bytree=0.5,
                            verbose=-1, n_jobs=2).fit(tr[feats + pc].fillna(0), tr.y)
    te["s_gbm"] = gb.predict_proba(te[feats + pc].fillna(0))[:, 1]
    # factorization model
    people = {u: k for k, u in enumerate(sorted(tr.person.unique()))}
    mu, sd = tr[feats].mean().values, tr[feats].std().values + 1e-9
    Xt, At, Pt, Gt, Yt = tensors(tr, Z, feats, people, mu, sd)
    Xe, Ae, Pe, Ge, Ye = tensors(te, Z, feats, people, mu, sd)
    net = Model(len(feats), Z.shape[1], len(people)); opt = torch.optim.Adam(net.parameters(), lr=0.01, weight_decay=1e-5)
    ng = int(Gt.max()) + 1
    for ep in range(60):
        opt.zero_grad(); loss = listwise(net(Xt, At, Pt), Gt, Yt, ng); loss.backward(); opt.step()
    with torch.no_grad():
        te["s_mf"] = net(Xe, Ae, Pe).numpy()
    te["s_blend"] = te.groupby(["person", "day"]).s_gbm.rank(pct=True) + te.groupby(["person", "day"]).s_mf.rank(pct=True)
    out = {"month": m, "people_with_taste": len(people), "test_people_seen": float(np.mean(Pe.numpy() >= 0))}
    for name in ("gbm", "mf", "blend"):
        hit, auc = [], []
        for _, g in te.groupby(["person", "day"]):
            if g.y.sum() == 0 or g.y.all():
                continue
            hit.append(g.y.values[np.argsort(-g["s_" + name].values)[:3]].any()); auc.append(roc_auc_score(g.y, g["s_" + name]))
        out[name] = {"top3_hit": round(100 * float(np.mean(hit)), 1), "auc": round(float(np.mean(auc)), 3), "n": len(hit)}
    print(json.dumps(out), flush=True)
    return out


def main(workers):
    PS.load(); traits()
    from . import harness
    harness.baseline()
    with mp.get_context("fork").Pool(workers) as pool:
        res = pool.map(month, MONTHS)
    summ = {k: {"top3_hit": round(float(np.mean([r[k]["top3_hit"] for r in res])), 1), "auc": round(float(np.mean([r[k]["auc"] for r in res])), 3)}
            for k in ("gbm", "mf", "blend")}
    json.dump({"summary": summ, "months": res}, open(f"{HERE}/reports/page_mf.json", "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
