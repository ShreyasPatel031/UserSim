"""Exposure-controlled user-sim checks (orchestrator Nov 11). On the PH agent's 19-day rows with E5 baseline scores:
(1) Hit@1 / Hit@3 on the full line-up for: random, E5 product-only taste, E5 full, ORACLE = rank by the day's final votes
    (non-personal, uses outcomes - reference only), and taste+oracle (z-sum, reference).
(2) the same inside exposure-controlled sets: each person-day restricted to the day's final top 10 / top 20 (person-days with
    >= 1 pick inside the set), against random inside the set.
(3) choice-variance shares on voting person-days: McFadden pseudo-R2 of a within-person-day logit (features centred within
    person-day; null = uniform choice in the line-up) for popularity (log final votes), taste, and both.
    python exposure_control.py <rows_scored.parquet> <launches dir> <out.json>"""
import glob, json, sys, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
ROWS, LD, OUT = sys.argv[1:4]
rng = np.random.default_rng(0)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(LD + "/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last")
rk = dict(zip(L.id, pd.to_numeric(L.daily_rank, errors="coerce"))); vt = dict(zip(L.id, pd.to_numeric(L.votes, errors="coerce")))
R = pd.read_parquet(ROWS); R["rank"] = R.launch_id.map(rk); R["lv"] = np.log1p(R.launch_id.map(vt).astype(float))
R = R[R["rank"].notna() & R.lv.notna()].copy()
R["rand"] = rng.random(len(R)); R["oracle"] = R.lv + rng.random(len(R)) * 1e-6
g = lambda c: R.groupby(["d", "person_id"])[c]
z = lambda c: (R[c] - g(c).transform("mean")) / (g(c).transform("std") + 1e-9)
R["taste_plus_oracle"] = z("product_only") + z("oracle")

def hits(D, s):
    D = D[D.groupby(["d", "person_id"]).y.transform("sum") > 0].copy()
    D["r"] = D.groupby(["d", "person_id"])[s].rank(ascending=False, method="first")
    h = D.groupby(["d", "person_id"]).apply(lambda x: pd.Series({"h1": float(x.y[x.r <= 1].sum() > 0), "h3": float(x.y[x.r <= 3].sum() > 0)}))
    return h.groupby(level=0).mean()

def boot(v, B=4000):
    v = np.asarray(v, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)]

res = {"rows": int(len(R)), "days": int(R.d.nunique()), "voting_person_days": int((R.groupby(["d", "person_id"]).y.sum() > 0).sum())}
for setname, D in (("full line-up", R), ("final top 20", R[R["rank"] <= 20]), ("final top 10", R[R["rank"] <= 10])):
    out = {"voting_person_days": int((D.groupby(["d", "person_id"]).y.sum() > 0).sum())}
    base = None
    for s in ("rand", "product_only", "full", "oracle", "taste_plus_oracle"):
        h = hits(D, s); out[s] = {"Hit@1": boot(h.h1), "Hit@3": boot(h.h3)}
        if s == "rand": base = h
        else: out[s]["Hit@3 minus random (paired)"] = boot(h.h3 - base.h3)
    res[setname] = out
# (3) pseudo-R2 on voting person-days
V = R[R.groupby(["d", "person_id"]).y.transform("sum") > 0].copy()
for c in ("lv", "product_only", "full"):
    V[c + "_c"] = V[c] - V.groupby(["d", "person_id"])[c].transform("mean")
    V[c + "_c"] /= V[c + "_c"].std() + 1e-9
n_l = V.groupby(["d", "person_id"]).y.transform("size"); k_l = V.groupby(["d", "person_id"]).y.transform("sum")
p0 = (k_l / n_l).clip(1e-6, 1 - 1e-6); ll0 = float(np.sum(V.y * np.log(p0) + (1 - V.y) * np.log(1 - p0)))
off = np.log(p0 / (1 - p0)).to_numpy()
import statsmodels.api as sm
def r2(cols):
    m = sm.GLM(V.y.to_numpy(), V[cols].to_numpy(), family=sm.families.Binomial(), offset=off).fit()
    return round(1 - m.llf / ll0, 4), [round(float(x), 3) for x in m.params]
res["pseudo_R2 (within person-day; null = each person-day's base rate)"] = {
    "popularity (log final votes; non-personal, outcome)": r2(["lv_c"]), "taste product-only": r2(["product_only_c"]),
    "taste full (incl. team ties)": r2(["full_c"]), "popularity + taste product-only": r2(["lv_c", "product_only_c"]),
    "popularity + taste full": r2(["lv_c", "full_c"])}
json.dump(res, open(OUT, "w"), indent=1); print(json.dumps(res, indent=1))
