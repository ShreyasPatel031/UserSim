"""Does the fuller upvote history (store v2: browser-scrolled histories for ~2,600 holdout people) help the person model?
Two steps, because store.load() reads SIMLAB_DATA at import:
  SIMLAB_DATA=data    python -m simlab.v2_compare dump v1
  SIMLAB_DATA=data_v2 python -m simlab.v2_compare dump v2
  python -m simlab.v2_compare compare            -> simlab/reports/v2_compare.json
Same Sep-train / Oct-test split and model as phase2 (popularity + relationships + simple taste + personas v1-v4 +
collaborative filtering on teams), scored on the v1 person-days so the comparison is like for like:
  v1               v1 features, v1 labels (tonight's number)
  v1 feat, v2 lab  v1 features scored against the fuller labels (measurement only)
  v2               v2 features and v2 labels (more backing ties, richer neighbours)
Also split by whether the person's history is now complete."""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
from . import choice
from .persona import CACHE
from .path90 import load

HERE = os.path.dirname(os.path.abspath(__file__))
PERS = {"p1": "taste_ratings.jsonl", "p2": "taste_v2_ratings.jsonl", "p3": "taste_v3_ratings.jsonl", "p4": "taste_best4_full.jsonl"}
BASE = ["pop", "backed", "topic", "meaning"]; CF = ["cf_team", "nbr_team", "nbr_pop"]


def dump(tag):
    from . import store
    from .phase2 import cf_features
    P, I, E = store.load(); D = choice.rows()
    for k, f in PERS.items():
        R = load(f"{CACHE}/{f}"); D[k] = [R.get(g, {}).get(i, np.nan) for g, i in zip(D.g, D.id)]
    D = cf_features(D, P, I, E)
    D.to_parquet(f"{CACHE}/rows_{tag}.parquet")
    print(tag, "person-days", D.g.nunique(), "picks", int(D.y.sum()))


def fit(tr, te, cols):
    m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1)
    return m.fit(tr[cols], tr.y).predict_proba(te[cols])[:, 1]


def compare():
    A = pd.read_parquet(f"{CACHE}/rows_v1.parquet"); B = pd.read_parquet(f"{CACHE}/rows_v2.parquet")
    keep = set(A.dropna(subset=list(PERS)).g)               # v1 person-days that have all four persona ratings
    key = ["g", "id"]
    B = B[B.g.isin(keep)]; A = A[A.g.isin(keep)]
    for D in (A, B):
        for k in PERS:
            D[k] = D.groupby("g")[k].rank(pct=True)
    A2 = A.drop(columns="y").merge(B[key + ["y"]], on=key, how="left").fillna({"y": 0})  # v1 features, v2 labels
    full = set(json.loads(l)["username"] for f in ("scroll_full", "scroll_sample", "scroll_upvotes")
               for l in __import__("gzip").open(f"{os.path.dirname(HERE)}/ph_predict/data/{f}.jsonl.gz"))
    res = []
    for fol in (False, True):
        cols = BASE + list(PERS) + CF + (["follow"] if fol else [])
        for name, D in (("v1", A), ("v1 features, v2 labels", A2), ("v2", B)):
            tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"].copy()
            te["p"] = fit(tr, te, cols)
            row = {"follows": fol, "data": name}
            for sub, T in (("all", te), ("scrolled people", te[te.person.isin(full)]), ("others", te[~te.person.isin(full)])):
                T = T[T.g.isin(T[T.y == 1].g)]                 # person-days with at least one real pick
                h, a = choice.person_metrics(T, T.p.values)
                row[sub] = {"top3_hit": round(h, 3), "auc": round(a, 3), "person_days": int(T.g.nunique()),
                            "picks_per_day": round(float(T.y.sum() / T.g.nunique()), 2)}
            res.append(row); print(json.dumps(row), flush=True)
    json.dump(res, open(f"{HERE}/reports/v2_compare.json", "w"), indent=1)


if __name__ == "__main__":
    dump(sys.argv[2]) if sys.argv[1] == "dump" else compare()
