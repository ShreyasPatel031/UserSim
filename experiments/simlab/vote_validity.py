"""Predictive validity of "likely voters" (Shreyas via orchestrator 01:55Z Nov 12; internal use only).
Features and people exactly as vote_match.py (fixed: explicit zeros removed so recency uses only upvotes dated before the launch
day). Scorers (logistic, month-forward: for test month m, fitted on 150 sampled launches of months May..m-1, negatives 20:1,
intercept corrected for the negative subsampling so probabilities are on the population scale):
  A  activity + recency        B  A + product taste (sim_soft, sim_mean) + topic        C  B + maker/hunter ties
Test launches: (i) the 114 Aug-Oct launches of voters_eval (>= 30 voters among the site 5,096), (ii) every ranked Aug-Oct launch.
1. Person level per launch: AUC, precision / recall at 100 / 500 / 2,000, lift = precision / base rate; calibration by decile of
   predicted probability (pooled); splits: cold makers (no earlier launch by any team member) vs repeat, final rank band
   (1-3, 4-10, 11+). Launch-bootstrap 95% CIs.
2. Launch level: predicted votes = sum of p over the pool (also top-2,000 sum, count p > 0.05); within-day Spearman with final
   votes; daily top 3/5/10; alone and added (ridge, month-forward on log) to the product-only ridge (landing_retrieval 'base')
   and to the honest full LM; paired by day. Set match: recall of real pool voters in the top 500 / 2,000.
3. Coverage: share of each test launch's final votes cast by pool people; person- and launch-level metrics with random 10 / 25 /
   50% subsamples of the pool.
    python vote_validity.py <v3 dir> <launches dir> <landing out dir (launch_emb256.npy, landing_rows.parquet)> <uses2 export> <honest_preds.parquet> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy import sparse
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import roc_auc_score

V3, LDIR, LAND, EXP, HON, OUT = sys.argv[1:7]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna() & (L.day < "2026-11-11")].copy().sort_values(["day", "id"]).reset_index(drop=True)
L["id"] = L.id.astype(str); E = np.load(os.path.join(LAND, "launch_emb256.npy")); assert len(E) == len(L)
L["tp"] = [set(json.loads(t)) if isinstance(t, str) and t.startswith("[") else set() for t in L.topics]
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set()) for m, p in zip(L.makers, L.poster)]
L["v"] = pd.to_numeric(L.votes, errors="coerce").astype(float); L["rank"] = L.daily_rank.astype(float)
lix = {i: k for k, i in enumerate(L.id)}; ldays = L.day.to_numpy(); dnum = pd.to_datetime(ldays).to_numpy().astype("datetime64[D]").astype(np.int64)
first_by_member = {}
for d, t in zip(L.day, L.team):
    for m in t: first_by_member[m] = min(first_by_member.get(m, "9999"), d)
L["cold"] = [not any(first_by_member.get(m, "9999") < d for m in t) for d, t in zip(L.day, L.team)]
comp = set(pd.read_parquet(os.path.join(V3, "persons.parquet")).query("complete").person_id)
ev = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"]).query("kind == 'upvote'")
ev = ev[ev.person_id.isin(comp)]; ev["target_id"] = ev.target_id.astype(str); ev = ev[ev.target_id.isin(lix)].drop_duplicates(["person_id", "target_id"])
people = sorted(ev.person_id.unique()); pix = {p: i for i, p in enumerate(people)}; NP = len(people)
M = sparse.csr_matrix((np.ones(len(ev)), (ev.person_id.map(pix), ev.target_id.map(lix))), shape=(NP, len(L))); MT = M.T.tocsr()
Pe = pd.read_parquet(os.path.join(EXP, "people.parquet")); site_people = np.array([pix[p] for p in Pe.person_id if p in pix]); site_set = set(site_people.tolist())
TPM = np.array([[1.0 if t in s else 0.0 for t in sorted({x for s in L.tp for x in s})] for s in L.tp], np.float32)
print("people", NP, "launches", len(L), flush=True)


def feats(k):
    prior = (dnum < dnum[k]).astype(float)
    s = E @ E[k]; Mp = M.multiply(prior).tocsr(); Mp.eliminate_zeros(); n = np.asarray(Mp.sum(1)).ravel()
    soft = np.log(Mp @ np.exp(20 * (s - 1)) + 1e-12) / 20 + 1; mean = (Mp @ s) / np.maximum(n, 1)
    tm = (TPM @ TPM[k] > 0).astype(float); topic = (Mp @ tm) / np.maximum(n, 1)
    tie = np.array([float(bool(t & L.team.iat[k])) for t in L.team]) if L.team.iat[k] else np.zeros(len(L)); tie[k] = 0
    ties = np.log1p(Mp @ tie)
    last = np.full(NP, -10 ** 9); c = Mp.tocoo(); np.maximum.at(last, c.row, dnum[c.col])
    rec = np.digitize(np.where(last < 0, 9999, dnum[k] - last), [7, 30, 90])
    return np.c_[np.where(n > 0, soft, 0), mean, topic, ties, np.log1p(n), rec].astype(np.float32)


COLS = ["sim_soft", "sim_mean", "topic", "ties", "act", "rec"]
SETS = {"A_activity_recency": [4, 5], "B_plus_taste_topic": [0, 1, 2, 4, 5], "C_plus_ties": [0, 1, 2, 3, 4, 5]}
voters = lambda k: MT[k].indices
cnt = np.diff(MT.indptr); FC = {}


def fit_for(month):
    if month in FC: return FC[month]
    pool = [k for k in range(len(L)) if "2026-05-01" <= ldays[k] < month and cnt[k] >= 5]
    Xs, ys, negs_total, negs_kept = [], [], 0, 0
    for k in rng.choice(pool, min(150, len(pool)), replace=False):
        X = feats(k); V = set(voters(k).tolist()); pos = list(V); neg_all = np.setdiff1d(np.arange(NP), pos)
        neg = rng.choice(neg_all, min(len(neg_all), 20 * max(1, len(pos))), replace=False)
        negs_total += len(neg_all); negs_kept += len(neg); Xs.append(X[pos + list(neg)]); ys += [1] * len(pos) + [0] * len(neg)
    Xtr, ytr = np.vstack(Xs), np.array(ys); mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9; corr = np.log(negs_kept / negs_total)
    mods = {nm: LogisticRegression(C=1.0, max_iter=3000).fit(((Xtr - mu) / sd)[:, c], ytr) for nm, c in SETS.items()}
    FC[month] = (mu, sd, corr, mods); print("fitted", month, flush=True); return FC[month]


def probs(k):
    mu, sd, corr, mods = fit_for(ldays[k][:7] + "-01"); X = feats(k); Z = (X - mu) / sd
    return {nm: 1 / (1 + np.exp(-(mods[nm].decision_function(Z[:, c]) + corr))) for nm, c in SETS.items()}, X


test_all = [k for k in range(len(L)) if "2026-08-01" <= ldays[k] <= "2026-10-31"]
test114 = {k for k in test_all if len(set(voters(k).tolist()) & site_set) >= 30}
SUBS = {f: rng.random(NP) < f for f in (0.10, 0.25, 0.50)}
rows, lrows, calib = [], [], []
for t, k in enumerate(test_all):
    P, X = probs(k); y = np.zeros(NP, bool); y[voters(k)] = True
    for nm, p in P.items():
        order = np.argsort(-p)
        r = {"k": k, "scorer": nm, "base": y.mean(), "auc": roc_auc_score(y, p) if 0 < y.sum() < NP else np.nan}
        for K in (100, 500, 2000):
            top = order[:K]; r[f"prec{K}"] = y[top].mean(); r[f"rec{K}"] = y[top].sum() / max(1, y.sum())
        rows.append(r)
        lr = {"k": k, "scorer": nm, "sum_p": p.sum(), "sum_top2000": p[order[:2000]].sum(), "n_above": int((p > 0.05).sum())}
        for f, m in SUBS.items():
            lr[f"sum_p_{int(f * 100)}"] = p[m].sum()
            ym, pm = y[m], p[m]; o2 = np.argsort(-pm)[: int(500 * f)]
            lr[f"prec500_{int(f * 100)}"] = ym[o2].mean() if len(o2) else np.nan
        lrows.append(lr)
        if t % 5 == 0:
            dec = np.minimum((np.argsort(np.argsort(p)) * 10) // NP, 9)
            for dd in range(10): calib.append({"scorer": nm, "dec": dd, "pred": p[dec == dd].mean(), "obs": y[dec == dd].mean()})
    if t % 200 == 0: print("launch", t, "/", len(test_all), flush=True)
D = pd.DataFrame(rows).merge(L[["cold", "rank"]].rename_axis("k").reset_index(), on="k")
D["band"] = pd.cut(D["rank"], [0, 3, 10, 1e9], labels=["top3", "4-10", "11+"]); D["in114"] = D.k.isin(test114)
LV = pd.DataFrame(lrows).merge(L[["day", "v", "rank", "id"]].rename_axis("k").reset_index(), on="k")
D.to_parquet(os.path.join(OUT, "person_rows.parquet")); LV.to_parquet(os.path.join(OUT, "launch_rows.parquet"))


def boot(v, B=2000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4), int(len(v))]


MET = ["auc", "prec100", "prec500", "prec2000", "rec100", "rec500", "rec2000"]
res = {"design": __doc__.split("\n    python")[0], "people": NP, "test_launches_all": len(test_all), "test_launches_114": len(test114), "person": {}}
for label, sub in (("114 launches", D[D.in114]), ("all Aug-Oct ranked", D)):
    out = {}
    for nm in SETS:
        g = sub[sub.scorer == nm]; o = {m: boot(g[m]) for m in MET}; o["lift100"] = boot(g.prec100 / g.base); o["lift500"] = boot(g.prec500 / g.base)
        out[nm] = o
    for a, b in (("B_plus_taste_topic", "A_activity_recency"), ("C_plus_ties", "A_activity_recency")):
        ga, gb = sub[sub.scorer == a].set_index("k"), sub[sub.scorer == b].set_index("k")
        out[f"{a} - {b} (paired)"] = {m: boot(ga[m] - gb[m]) for m in ("auc", "prec100", "prec500", "rec2000")}
    for split, col in (("cold vs repeat", "cold"), ("rank band", "band")):
        out[split] = {f"{nm} | {v}": {m: boot(g[m]) for m in ("auc", "prec100", "rec2000")} for nm in SETS for v, g in sub[sub.scorer == nm].groupby(col, observed=True)}
    res["person"][label] = out
CB = pd.DataFrame(calib).groupby(["scorer", "dec"]).mean().round(5).reset_index()
res["calibration (pooled deciles of predicted p)"] = {nm: g[["dec", "pred", "obs"]].values.tolist() for nm, g in CB.groupby("scorer")}

# ---------- launch level
base = pd.read_parquet(os.path.join(LAND, "landing_rows.parquet"))[["id", "base"]]; base["id"] = base.id.astype(str)
H = pd.read_parquet(HON)[["id", "honest"]]; H["id"] = H.id.astype(str)
LW = LV.pivot_table(index=["k", "id", "day", "v", "rank"], columns="scorer", values=["sum_p", "sum_top2000", "n_above"]).reset_index()
LW.columns = ["_".join([c for c in col if c]) for col in LW.columns]
LW = LW.merge(base, on="id", how="left").merge(H, on="id", how="left"); LW["mon"] = LW.day.str[:7]


def per_day(df, col):
    out = {}
    for d, g in df.groupby("day"):
        if len(g) >= 10 and g[col].notna().all():
            out[d] = [spearmanr(g[col], g.v).correlation * 100] + [len(set(g.nlargest(k, col).id) & set(g.nsmallest(k, "rank").id)) / k * 100 for k in (3, 5, 10)]
    return pd.DataFrame(out, index=["spearman", "top3", "top5", "top10"]).T


def dboot(D_, B=2000):
    v = D_.values; bs = np.array([v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(B)])
    return {c: [round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j, c in enumerate(D_.columns)} | {"days": int(len(v))}


def stacked(ref, extra):                         # ridge(ref + log extra) month-forward over the test months (first month trains)
    out = pd.Series(np.nan, index=LW.index); mons = sorted(LW.mon.unique())
    for m in mons[1:]:
        tr, te = LW[(LW.mon < m) & LW[ref].notna()], LW[(LW.mon == m) & LW[ref].notna()]
        cols = [ref] + [f"l_{e}" for e in extra]
        for e in extra: LW[f"l_{e}"] = np.log(LW[e] + 1e-3)
        tr, te = LW.loc[tr.index], LW.loc[te.index]
        out[te.index] = Ridge(alpha=1.0).fit(tr[cols], np.log1p(tr.v)).predict(te[cols])
    return out


resL = {}
for nm in SETS:
    resL[f"{nm} sum_p alone"] = dboot(per_day(LW, f"sum_p_{nm}")); resL[f"{nm} top-2000 sum alone"] = dboot(per_day(LW, f"sum_top2000_{nm}"))
for ref, lab in (("base", "product-only ridge"), ("honest", "full LM")):
    R0 = per_day(LW[LW.mon > sorted(LW.mon.unique())[0]], ref); resL[lab] = dboot(R0)
    for nm in SETS:
        LW[f"st_{ref}_{nm}"] = stacked(ref, [f"sum_p_{nm}"]); R1 = per_day(LW, f"st_{ref}_{nm}"); j = R0.index.intersection(R1.index)
        resL[f"{lab} + {nm} sum_p"] = dboot(R1.loc[j]); resL[f"{lab} + {nm} sum_p - {lab} (paired)"] = dboot(R1.loc[j] - R0.loc[j])
res["launch"] = resL
pv = pd.DataFrame([{"k": k, "pool_voters": len(voters(k)), "votes": L.v.iat[k]} for k in test_all])
res["coverage"] = {"share of final votes cast by pool people (median, IQR)": [round(float(x), 3) for x in np.percentile(pv.pool_voters / pv.votes, [50, 25, 75])],
                   "pool voters per launch (median)": float(pv.pool_voters.median())}
sub = {}
for f in (10, 25, 50):
    sub[f"{f}% pool"] = {"prec500 (scaled K) by scorer": {nm: boot(LV[LV.scorer == nm][f"prec500_{f}"]) for nm in SETS},
                         "launch spearman sum_p by scorer": {nm: dboot(per_day(LW.assign(**{"_x": LV[LV.scorer == nm].set_index("k")[f"sum_p_{f}"].reindex(LW.k).values}), "_x"))["spearman"] for nm in SETS}}
res["coverage"]["subsamples"] = sub
json.dump(res, open(os.path.join(OUT, "vote_validity.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k not in ("design",)}, default=str)[:6000])
