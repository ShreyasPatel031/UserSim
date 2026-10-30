"""Do Gemini persona ratings raise the launch score, not just person picks? Persona ratings exist for Sep-Oct and ~340
people a day, so the population simulation is run over the rated people only, with and without the ratings
(same people, same weights). Train on September person-days (people who voted, rated), test on October days over
everyone rated that day who was active in the 30 days before (weighted by activity, as popscore).
  person+page+taste   popscore TASTE inputs
  + persona           + the 5 persona designs' ratings (pr_*)
Reports daily top-3/5 recall of the rated-people simulation vs real final rank, and the same with real picks of those
people (ceiling for this sample).
usage: python -m simlab.persona_launch -> reports/persona_launch.json"""
import json, os
import numpy as np, pandas as pd, lightgbm as lgb
from . import choice, popscore as PS
from .page_choice import page_table
from .page_taste import add_taste, traits

HERE = os.path.dirname(os.path.abspath(__file__))


def ratings():
    from pipeline import warehouse as W
    R = W.connect(do_sync=False).execute("SELECT person, day, launch_id AS id, design, rating FROM persona_ratings").df()
    R["id"] = R.id.astype(str)
    return R.pivot_table(index=["person", "day", "id"], columns="design", values="rating").add_prefix("pr_").reset_index()


def main():
    PS.load(); traits()
    from . import harness
    B = harness.baseline()
    R = ratings(); pr = [c for c in R.columns if c.startswith("pr_")]
    rated = set(zip(R.person, R.day))
    T = page_table(); pc = list(T.columns)
    cf = PS.fit_cf("2026-09-01")

    def prep(D):
        D = D[[(u, d) in rated for u, d in zip(D.person, D.day)]].copy()
        D = PS.featurize(D, cf, "2026-09-01"); D, tc = add_taste(D)
        D = D.join(T, on="id").merge(R, on=["person", "day", "id"], how="left")
        return D, tc
    tr, tc = prep(choice.rows(day_from="2026-09-01", day_to="2026-09-30"))
    te, _ = prep(choice.rows(day_from="2026-10-01", day_to="2026-10-24", all_people=True))
    res = {"train_rows": len(tr), "test_rows": len(te), "test_people_days": int(te.g.nunique())}
    for name, cols in (("person+page+taste", PS.FEATS + pc + tc), ("+ persona", PS.FEATS + pc + tc + pr)):
        m = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=50, colsample_bytree=0.5,
                               verbose=-1, n_jobs=8).fit(tr[cols], tr.y)
        te["s_" + name] = m.predict_proba(te[cols])[:, 1] * te.w
    te["s_real picks (ceiling)"] = te.y * te.w
    S = te.groupby(["day", "id"])[[c for c in te if c.startswith("s_")]].sum().reset_index()
    S = S.merge(B[["id", "dailyRank"]].drop_duplicates("id"), on="id")
    for c in [c for c in S if c.startswith("s_")]:
        res[c[2:]] = {f"top{k}": round(100 * float(np.mean([len(set(g.nlargest(k, c).id) & set(g[g.dailyRank <= k].id)) / k
                                                         for _, g in S.groupby("day") if (g.dailyRank <= k).sum() == k])), 1) for k in (3, 5)}
    res["days"] = int(S.day.nunique())
    json.dump(res, open(f"{HERE}/reports/persona_launch.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
