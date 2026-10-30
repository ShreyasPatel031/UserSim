"""(ABLATE=1: which person data carries the signal: drop one input group at a time, 300 people/day classifier.)
Stronger per-person pick models on the page_taste.py test (same person, day and line-up; train previous month, test
next). All use person + page + taste inputs; they differ in training data and learner:
  base      LightGBM classifier, 300 people/day, 400 trees, 31 leaves (page_taste.py)
  more      same, 1,000 people/day
  big       1,000 people/day, 1,200 trees, 63 leaves, lr 0.03
  rank      LambdaRank per person-day (listwise), 1,000 people/day
  rank_big  LambdaRank, 1,200 trees, 63 leaves
usage: python -m simlab.pick_boost [workers] -> reports/pick_boost.json"""
import json, os, sys
import multiprocessing as mp
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score
from . import choice, popscore as PS
from .page_choice import page_table
from .page_taste import add_taste, traits, MONTHS

HERE = os.path.dirname(os.path.abspath(__file__))


def month(m):
    prev = PS.month_start(m, 1); cf = PS.fit_cf(prev); rng = np.random.default_rng(0)

    def sample(D, n):
        keep = set()
        for d, g in D.groupby("day"):
            keep |= {u + "|" + d for u in rng.permutation(g.person.unique())[:n]}
        return D[(D.person + "|" + D.day).isin(keep)].copy()
    full = choice.rows(day_from=prev, day_to=PS.month_end(prev[:7]))
    te = sample(choice.rows(day_from=m + "-01", day_to=PS.month_end(m)), 200)
    T = page_table(); pc = list(T.columns)
    te = PS.featurize(te, cf, prev); te, tc = add_taste(te); te = te.join(T, on="id")
    cols = PS.FEATS + pc + tc; out = {"month": m}
    trs = {}
    for n in ((300,) if os.environ.get("ABLATE") == "1" else (300, 1000)):
        tr = PS.featurize(sample(full, n), cf, prev); tr, _ = add_taste(tr); trs[n] = tr.join(T, on="id").sort_values(["g"])
    groups = {"team": ["backed", "cf_team", "nbr_team", "nbr_pop", "team_recent"], "sequence": [c for c in PS.FEATS if c.startswith("seq_")],
              "category": [c for c in PS.FEATS if c.startswith("cat_")], "content": ["topic", "meaning"] + pc + tc}
    if os.environ.get("ABLATE") == "1":
        specs = {"base": (300, "clf", 400, 31, 0.05)}
        for k, v in groups.items():
            specs["-" + k] = specs["only " + k] = (300, "clf", 400, 31, 0.05)
    else:
      specs = {"base": (300, "clf", 400, 31, 0.05), "more": (1000, "clf", 400, 31, 0.05), "big": (1000, "clf", 1200, 63, 0.03),
             "rank": (1000, "rank", 400, 31, 0.05), "rank_big": (1000, "rank", 1200, 63, 0.03)}
    for name, (n, kind, nt, nl, lr) in specs.items():
        cols = PS.FEATS + pc + tc
        if name.startswith("-"):
            cols = [c for c in cols if c not in groups[name[1:]]]
        elif name.startswith("only "):
            cols = groups[name[5:]]
        tr = trs[n]; kw = dict(n_estimators=nt, learning_rate=lr, num_leaves=nl, min_child_samples=50, colsample_bytree=0.5, verbose=-1, n_jobs=2)
        if kind == "clf":
            te["s_" + name] = lgb.LGBMClassifier(**kw).fit(tr[cols], tr.y).predict_proba(te[cols])[:, 1]
        else:
            grp = tr.groupby("g", sort=False).size().values
            te["s_" + name] = lgb.LGBMRanker(objective="lambdarank", **kw).fit(tr[cols], tr.y, group=grp).predict(te[cols])
    for name in specs:
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
    names = [k for k in res[0] if isinstance(res[0][k], dict)]
    summ = {k: {"top3_hit": round(float(np.mean([r[k]["top3_hit"] for r in res])), 1), "auc": round(float(np.mean([r[k]["auc"] for r in res])), 3),
                "months_better_than_base": sum(r[k]["auc"] > r["base"]["auc"] for r in res)} for k in names}
    json.dump({"summary": summ, "months": res}, open(f"{HERE}/reports/pick_{'ablate' if os.environ.get('ABLATE') == '1' else 'boost'}.json", "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
