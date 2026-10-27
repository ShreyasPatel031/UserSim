"""Person-level hit at top 1 / 3 / 5 / 10: is any of the person's real picks in our top k for them that day?
Models: random, popularity only, today's best before launch (v2 + personas + collaborative filtering + sequence), and
the same + early read (others' comments in the first 3 h). With and without the undated follow lists.
Same v1 person-days, Sep train / Oct test. usage: SIMLAB_DATA=data_v2 python -m simlab.topk -> reports/topk.json"""
import json, os
import numpy as np, pandas as pd
from . import store
from .seq import features
from .visit import comments
from .v2_compare import PERS, BASE, CF, fit
from .persona import CACHE

HERE = os.path.dirname(os.path.abspath(__file__))
SEQ = ["seq_last10", "seq_decay", "seq_nn", "team_recent"]
KS = (1, 3, 5, 10)


def early_read(D, I, hours=3):
    C = comments(I); C["t"] = C.t.dt.tz_localize(None)
    cut = {d: (pd.Timestamp(d + "T00:01:00-07:00").tz_convert("UTC") + pd.Timedelta(hours=hours)).tz_localize(None) for d in I.day.unique()}
    C = C[C.t < C.id.map(dict(zip(I.id, I.day))).map(cut)]
    n = C.groupby("id").size().to_dict(); own = C.groupby(["id", "person"]).size().to_dict()
    D["early3h"] = np.log1p([n.get(x, 0) - own.get((x, u), 0) for x, u in zip(D.id, D.person)])
    D["early3h_r"] = D.groupby("g").early3h.rank(pct=True)
    return D


def hits(te, p):
    t = te.assign(p=p); t["r"] = t.groupby("g").p.rank(ascending=False, method="first")
    return {k: round(float(t[t.r <= k].groupby("g").y.max().reindex(t.g.unique(), fill_value=0).mean()), 3) for k in KS}


def main():
    P, I, E = store.load()
    A = pd.read_parquet(f"{CACHE}/rows_v1.parquet", columns=["g"] + list(PERS)); keep = set(A.dropna(subset=list(PERS)).g)
    D = pd.read_parquet(f"{CACHE}/rows_v2.parquet"); D = D[D.g.isin(keep)].copy()
    for k in PERS:
        D[k] = D.groupby("g")[k].rank(pct=True)
    D = early_read(features(D, I, E), I)
    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"].copy(); te = te[te.g.isin(te[te.y == 1].g)]
    best = BASE + list(PERS) + CF + SEQ
    res = {"test_person_days": int(te.g.nunique()), "launches_per_day_mean": round(float(te.groupby("g").size().mean()), 1),
           "picks_per_day_mean": round(float(te.groupby("g").y.sum().mean()), 2),
           "random": hits(te, np.random.default_rng(0).random(len(te))), "popularity only": hits(te, te["pop"].values)}
    for fol in (False, True):
        F = ["follow"] if fol else []
        for name, cols in (("best before launch", best), ("+ early read 3 h", best + ["early3h", "early3h_r"])):
            res[f"{name} | {'follows' if fol else 'no follows'}"] = hits(te, fit(tr, te, cols + F))
    json.dump(res, open(f"{HERE}/reports/topk.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
