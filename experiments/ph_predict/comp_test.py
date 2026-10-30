"""Given competitors launching in the same day / week / month, which gets the most votes? Competitors = launches
sharing a specific topic (the 6 most common, generic topics are ignored). For every launch, groups of 3 = it + 2 competitors in the same window; predict the
top-voted one. Out of sample everywhere (rolling monthly, Jul-Oct). Three predictors, as the honesty rule asks:
  simulation only   LightGBM on simulation outputs only (pst_ person sim with page + taste, tpd_ reach x conversion)
  launch only       ctrl.py launch model, all inputs, no simulation
  both              launch model + simulation (stacked, trained on earlier months)
Random = 33.3%. Also accuracy on pairs (random 50%).
usage: python comp_test.py -> results/comp_test.json"""
import json
from collections import Counter
import numpy as np, pandas as pd, lightgbm as lgb

def load(p):
    return pd.DataFrame.from_dict(json.load(open(f"data/{p}_features.json")), orient="index").rename_axis("id").reset_index()
C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str)
A = C[["id", "day", "dailyRank", "logv", "all"]].merge(load("pst"), on="id").merge(load("tpd"), on="id")
for c in [c for c in A if c.startswith("pst_") and not c.endswith("pmax")]:
    A[c] = np.log1p(A[c])
sc = [c for c in A if c.startswith(("pst_", "tpd_"))]
A["mon"] = A.day.str[:7]; A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V")
out = []
for m in sorted(A.mon.unique())[1:]:
    tr, te = A[A.mon < m], A[A.mon == m].copy()
    fit = lambda cols, y: np.mean([lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1,
                                                     colsample_bytree=0.5, random_state=s, verbose=-1, n_jobs=8).fit(tr[cols], tr[y]).predict(te[cols]) for s in range(3)], 0)
    te["simulation only"] = fit(sc, "logv"); te["both"] = fit(sc + ["all"], "logv"); out.append(te)
T = pd.concat(out).rename(columns={"all": "launch only"})
# competitors by topic
days = {}
import glob
for f in glob.glob("data/days/*.json"):
    for p in json.load(open(f)):
        t = p.get("topics") or []
        t = [e["node"]["name"] for e in t.get("edges", [])] if isinstance(t, dict) else [x["name"] if isinstance(x, dict) else x for x in t]
        days[str(p["id"])] = t
T["topics"] = T.id.map(lambda i: days.get(i, []))
freq = Counter(t for ts in T.topics for t in ts); generic = {t for t, _ in freq.most_common(6)}
T["spec"] = T.topics.map(lambda ts: [t for t in ts if t not in generic])
rng = np.random.default_rng(0); P = ["simulation only", "launch only", "both"]
res = {"months_tested": sorted(T.mon.unique()), "launches": len(T), "generic_topics_ignored": sorted(generic)}
for win in ("day", "week", "mon"):
    trip, pair = {p: [] for p in P}, {p: [] for p in P}
    for _, g in T.groupby(win):
        g = g.reset_index(drop=True); bytopic = {}
        for i, ts in enumerate(g.spec):
            for t in ts:
                bytopic.setdefault(t, []).append(i)
        for i in range(len(g)):
            comp = sorted({j for t in g.spec[i] for j in bytopic[t] if j != i})
            if len(comp) < 2:
                continue
            js = list(rng.choice(comp, 2, replace=False)); grp = g.loc[[i] + js]
            if grp.logv.nunique() < 3:
                continue
            win_id = grp.logv.idxmax()
            for p in P:
                trip[p].append(grp[p].idxmax() == win_id)
                a, b = g.loc[i], g.loc[js[0]]
                if a.logv != b.logv:
                    pair[p].append((a[p] > b[p]) == (a.logv > b.logv))
    res[win] = {"groups_of_3": len(trip[P[0]]), **{f"{p} (3)": round(100 * float(np.mean(trip[p])), 1) for p in P},
                **{f"{p} (pair)": round(100 * float(np.mean(pair[p])), 1) for p in P}}
json.dump(res, open("results/comp_test.json", "w"), indent=1); print(json.dumps(res, indent=1))
