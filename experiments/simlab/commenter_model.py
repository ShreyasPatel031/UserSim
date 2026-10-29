"""Who will comment on a launch: LightGBM trained on the previous month's person x launch rows, tested on the next.
Inputs, all dated before the launch day: the person's activity (w), the person model's choice score (p), past backing
of the team, follows the team, and the person's comments / upvotes in the 7 and 30 days before.
Scored like eval_commenters.py: share of real commenters in each launch's top 100, AUC.
usage: python -m simlab.commenter_model -> reports/commenter_model.json"""
import glob, json, os
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score
from pipeline import warehouse as W

HERE = os.path.dirname(os.path.abspath(__file__))
FEATS = ["w", "p", "backed", "follow", "c7", "c30", "u7", "u30", "c_share"]


def activity(con):
    E = con.execute("SELECT person, date, kind FROM events").df()
    E["date"] = pd.to_datetime(E.date)
    return {k: g.groupby("person").date.apply(lambda s: np.sort(s.values)) for k, g in E.groupby("kind")}


GAP = int(os.environ.get("GAP_DAYS", "0"))   # leakage check: leave out the last GAP days before the launch


def count_before(arrs, people, day, days):
    d1 = np.datetime64(day) - np.timedelta64(GAP, "D"); d0 = d1 - np.timedelta64(days, "D")
    return np.array([(lambda a: np.searchsorted(a, d1) - np.searchsorted(a, d0))(arrs.get(u, np.array([], "datetime64[ns]"))) for u in people])


def rows(con):
    act = activity(con)
    com = set(map(tuple, con.execute("SELECT DISTINCT person, launch_id FROM events WHERE kind = 'comment'").fetchall()))
    out = []
    for f in sorted(glob.glob(f"{HERE}/cache/popscore/rows/*.parquet")):
        day = os.path.basename(f)[:10]
        D = pd.read_parquet(f); D["id"] = D.id.astype(str); D["day"] = day
        ppl = D.person.unique()
        for k, kind in (("c", "comment"), ("u", "upvote")):
            for n in (7, 30):
                m = dict(zip(ppl, count_before(act.get(kind, {}), ppl, day, n)))
                D[f"{k}{n}"] = D.person.map(m)
        D["c_share"] = D.c30 / (D.c30 + D.u30 + 1)
        D["y"] = [(u, x) in com for u, x in zip(D.person, D.id)]
        out.append(D)
    return pd.concat(out)


def main():
    con = W.connect(do_sync=False)
    R = rows(con); R["mon"] = R.day.str[:7]
    months = sorted(R.mon.unique())
    res = {k: [] for k in ("trained", "model_x_activity", "activity")}; auc = {k: [] for k in res}
    for m_prev, m in zip(months, months[1:]):
        tr, te = R[R.mon == m_prev], R[R.mon == m]
        neg = tr[~tr.y].sample(min(len(tr[~tr.y]), 2_000_000), random_state=0)
        tr = pd.concat([tr[tr.y], neg])
        clf = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=100, verbose=-1, n_jobs=32)
        clf.fit(tr[FEATS], tr.y)
        print(m, "gain", dict(zip(FEATS, clf.booster_.feature_importance("gain").round())), flush=True)
        te = te.assign(s=clf.predict_proba(te[FEATS])[:, 1], px=te.p * te.w)
        for x, g in te.groupby("id"):
            k = int(g.y.sum())
            if k == 0 or len(g) < 200:
                continue
            for name, col in (("trained", "s"), ("model_x_activity", "px"), ("activity", "w")):
                res[name].append(g.y.values[np.argsort(-g[col].values)[:100]].sum() / k)
                auc[name].append(roc_auc_score(g.y, g[col]))
        print(m, {k: round(float(np.mean(v)), 3) for k, v in res.items()}, flush=True)
    out = {"share_of_real_commenters_in_top100": {k: round(float(np.mean(v)), 3) for k, v in res.items()},
           "auc": {k: round(float(np.mean(v)), 3) for k, v in auc.items()}, "launches": len(res["trained"])}
    json.dump(out, open(f"{HERE}/reports/commenter_model{'_gap' + str(GAP) if GAP else ''}.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
