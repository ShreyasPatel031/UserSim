"""The built-in A/B test: each active person sees the same day's line-up and picks a few. With the person, the day and
the line-up held fixed, do the launch pages (what a maker can change) predict which launches each person picks, beyond
the person's taste, ties to the team and history (the person model's inputs)?
Per month m (May-Oct): train on the previous month's person-days, test on m. Two models, same rows:
  person      the person model's inputs (popscore.FEATS: backing, topic, meaning, collaborative, sequence, category)
  person+page the same plus every launch-page input (ps_* Gemini element scores, pf_* page facts, vs_* video)
Scores: top-3 hit (a real pick in the person's top 3), AUC within person-day, and how far each page input moves picks.
usage: python -m simlab.page_choice [workers] -> reports/page_choice.json"""
import json, os, sys
import multiprocessing as mp
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score
from . import choice, popscore as PS

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.join(os.path.dirname(HERE), "ph_predict", "data")
MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]


def page_table():
    T = None
    for f in ("ps_features.json", "pf_features.json", "vs_features.json"):
        p = f"{PH}/{f}"
        if os.path.exists(p):
            d = pd.DataFrame.from_dict(json.load(open(p)), orient="index")
            T = d if T is None else T.join(d, how="outer")
    T.index = T.index.astype(str)
    return T


def month(m):
    prev = PS.month_start(m, 1)
    cf = PS.fit_cf(prev)
    rng = np.random.default_rng(0)

    def sample(D, n):
        keep = set()
        for d, g in D.groupby("day"):
            keep |= {u + "|" + d for u in rng.permutation(g.person.unique())[:n]}
        return D[(D.person + "|" + D.day).isin(keep)].copy()
    tr = sample(choice.rows(day_from=prev, day_to=PS.month_end(prev[:7])), 300)
    te = sample(choice.rows(day_from=m + "-01", day_to=PS.month_end(m)), 200)
    tr, te = PS.featurize(tr, cf, prev), PS.featurize(te, cf, prev)
    T = page_table()
    for D in (tr, te):
        D["id"] = D.id.astype(str)
    pc = list(T.columns)
    tr = tr.join(T, on="id"); te = te.join(T, on="id")
    out = {"month": m, "train_rows": len(tr), "test_person_days": int(te.groupby(["person", "day"]).ngroups)}
    for name, cols in (("person", PS.FEATS), ("person+page", PS.FEATS + pc)):
        mdl = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, colsample_bytree=0.5,
                                 verbose=-1, n_jobs=1).fit(tr[cols], tr.y)
        te["s_" + name] = mdl.predict_proba(te[cols])[:, 1]
        if name == "person+page":
            g = dict(zip(cols, mdl.booster_.feature_importance("gain")))
            out["page_gain_share"] = round(sum(v for k, v in g.items() if k in pc) / sum(g.values()), 3)
            out["top_page_inputs"] = sorted(((k, round(float(v))) for k, v in g.items() if k in pc), key=lambda kv: -kv[1])[:15]
    for name in ("person", "person+page"):
        hit, auc = [], []
        for _, g in te.groupby(["person", "day"]):
            if g.y.sum() == 0 or g.y.all():
                continue
            hit.append(g.y.values[np.argsort(-g["s_" + name].values)[:3]].any())
            auc.append(roc_auc_score(g.y, g["s_" + name]))
        out[name] = {"top3_hit": round(100 * float(np.mean(hit)), 1), "auc": round(float(np.mean(auc)), 3), "n": len(hit)}
    te[["person", "day", "id", "y", "s_person", "s_person+page"]].to_parquet(f"{HERE}/cache/page_choice_{m}.parquet")
    print(json.dumps(out), flush=True)
    return out


def main(workers):
    os.makedirs(f"{HERE}/cache", exist_ok=True)
    PS.load()
    from . import harness
    harness.baseline()
    with mp.get_context("fork").Pool(workers) as pool:
        res = pool.map(month, MONTHS)
    summ = {k: {"top3_hit": round(float(np.mean([r[k]["top3_hit"] for r in res])), 1), "auc": round(float(np.mean([r[k]["auc"] for r in res])), 3),
                "person_days": int(sum(r[k]["n"] for r in res))} for k in ("person", "person+page")}
    summ["months_better"] = sum(r["person+page"]["auc"] > r["person"]["auc"] for r in res)
    json.dump({"summary": summ, "months": res}, open(f"{HERE}/reports/page_choice.json", "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
