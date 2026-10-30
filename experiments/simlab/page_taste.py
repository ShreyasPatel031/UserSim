"""Different people react differently to the same page. For each person and day, their taste for page traits = the
average page profile (every ps_/pf_/vs_ input, standardized) of the launches they picked BEFORE that day. Matched
against each launch in the day's line-up: overall match (dot product, cosine) and one match per trait (taste x page).
Same within-person test as page_choice.py (same person, same day, same line-up; train previous month, test next):
  person          the person model's inputs
  person+page     + every page input (what the page is)
  person+page+taste + the person's taste for page traits matched to this page (who reacts to it)
usage: python -m simlab.page_taste [workers] -> reports/page_taste.json"""
import json, os, sys
import multiprocessing as mp
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score
from . import choice, popscore as PS
from .page_choice import page_table

HERE = os.path.dirname(os.path.abspath(__file__))
MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
G = {}


def traits():
    if "Z" not in G:
        T = page_table()
        T = T.loc[:, T.notna().mean() > 0.05]
        Z = (T - T.mean()) / (T.std() + 1e-9)
        G["Z"] = Z.fillna(0.0).astype(np.float32)
        E = PS.load()["E"]
        E = E[E.item.astype(str).isin(G["Z"].index)].copy(); E["item"] = E.item.astype(str)
        G["hist"] = {u: (g.date.values, g.item.values) for u, g in E.sort_values("date").groupby("person")}
    return G["Z"], G["hist"]


def add_taste(D):
    Z, hist = traits()
    zi = {x: k for k, x in enumerate(Z.index)}; M = Z.values
    D = D.copy(); D["id"] = D.id.astype(str)
    prof = {}
    for (u, d) in set(zip(D.person, D.day)):
        h = hist.get(u)
        if h is None:
            continue
        k = np.searchsorted(h[0], d)                       # picks strictly before the day
        idx = [zi[x] for x in h[1][:k] if x in zi]
        if idx:
            prof[(u, d)] = M[idx].mean(0)
    P = np.array([prof.get((u, d), np.zeros(M.shape[1], np.float32)) for u, d in zip(D.person, D.day)], np.float32)
    X = np.array([M[zi[x]] if x in zi else np.zeros(M.shape[1], np.float32) for x in D.id], np.float32)
    D["taste_dot"] = (P * X).sum(1)
    D["taste_cos"] = D.taste_dot / (np.linalg.norm(P, axis=1) * np.linalg.norm(X, axis=1) + 1e-9)
    D["taste_n"] = [len(hist.get(u, ((), ()))[0]) for u in D.person]
    cols = [f"tx_{c}" for c in Z.columns]
    D = pd.concat([D.reset_index(drop=True), pd.DataFrame(P * X, columns=cols)], axis=1)
    return D, ["taste_dot", "taste_cos", "taste_n"] + cols


def month(m):
    prev = PS.month_start(m, 1); cf = PS.fit_cf(prev); rng = np.random.default_rng(0)

    def sample(D, n):
        keep = set()
        for d, g in D.groupby("day"):
            keep |= {u + "|" + d for u in rng.permutation(g.person.unique())[:n]}
        return D[(D.person + "|" + D.day).isin(keep)].copy()
    tr = sample(choice.rows(day_from=prev, day_to=PS.month_end(prev[:7])), 300)
    te = sample(choice.rows(day_from=m + "-01", day_to=PS.month_end(m)), 200)
    tr, te = PS.featurize(tr, cf, prev), PS.featurize(te, cf, prev)
    T = page_table(); pc = list(T.columns)
    tr, tc = add_taste(tr); te, _ = add_taste(te)
    tr = tr.join(T, on="id"); te = te.join(T, on="id")
    out = {"month": m}
    for name, cols in (("person", PS.FEATS), ("person+page", PS.FEATS + pc), ("person+page+taste", PS.FEATS + pc + tc)):
        mdl = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=50, colsample_bytree=0.5,
                                 verbose=-1, n_jobs=2).fit(tr[cols], tr.y)
        te["s_" + name] = mdl.predict_proba(te[cols])[:, 1]
        if name == "person+page+taste":
            g = dict(zip(cols, mdl.booster_.feature_importance("gain")))
            out["taste_gain_share"] = round(sum(v for k, v in g.items() if k in tc) / sum(g.values()), 3)
            out["top_taste_inputs"] = sorted(((k, round(float(v))) for k, v in g.items() if k in tc), key=lambda kv: -kv[1])[:12]
    for name in ("person", "person+page", "person+page+taste"):
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
    names = ("person", "person+page", "person+page+taste")
    summ = {k: {"top3_hit": round(float(np.mean([r[k]["top3_hit"] for r in res])), 1),
                "auc": round(float(np.mean([r[k]["auc"] for r in res])), 3)} for k in names}
    summ["months_taste_better_than_page"] = sum(r["person+page+taste"]["auc"] > r["person+page"]["auc"] for r in res)
    json.dump({"summary": summ, "months": res}, open(f"{HERE}/reports/page_taste.json", "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
