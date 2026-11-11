"""Reference table for the user-simulation goal (orchestrator Nov 11): E5 two-level baseline scored on the PH agent's
clean it-rows (tmp/e5/tl_cp_clean_rows.parquet: 12 clean days, people active 30 d before d, label-filtered), two input sets:
  product-only : taste_topic, taste_text (product text/topics vs the person's own history) + the person's activity
                 (act_30d, act_hist, tenure, comments_hist)
  full         : product-only + PH context (tie_backed_team, is_team). No follows in either.
Metrics (person level primary): Hit@1/Hit@3 per voting person-day, within-line-up AUC per person-day, voter R-precision per
product (by P), calibration (deciles, ECE, log-loss) on all rows; day-bootstrap 95% CIs. Population top 3/5/10 secondary.
    python usersim_ref_table.py <workdir> <rows.parquet>"""
import json, sys, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, log_loss
W, ROWS = sys.argv[1], sys.argv[2]
src = open(__file__.replace("usersim_ref_table.py", "two_level_baseline.py")).read().split("report = {")[0]
sys.argv = ["x", W]; G = {"__name__": "tlb"}; exec(compile(src, "tlb", "exec"), G)
FE = G["FEATS"]; SETS = {"product_only": ["taste_topic", "taste_text", "act_30d", "act_hist", "tenure", "comments_hist"],
                         "full": ["taste_topic", "taste_text", "tie_backed_team", "is_team", "act_30d", "act_hist", "tenure", "comments_hist"]}
R = pd.read_parquet(ROWS); R["li"] = R.launch_id.map(G["lid"])
rng = np.random.default_rng(0)
feats = {}   # (p, d) -> (idx, X)
for (p, d), _ in R.groupby(["person_id", "d"]):
    r = G["day_rows"](p, d, False)
    if r is None:
        idx = np.where(G["Lday"] == d)[0]; r = (idx, np.zeros((len(idx), len(FE)), np.float32))
    feats[(p, d)] = r
print("features for", len(feats), "person-days", flush=True)
for name, tr0, tr1, te0, te1 in G["FOLDS"]:
    days_all = set(G["Lday"]); tr_days = [str(x.date()) for x in pd.date_range(tr0, tr1) if str(x.date()) in days_all]
    Xtr, Ytr, wtr = G["build"](tr_days, sorted(G["comp"]), False, True)
    for sn, cols in SETS.items():
        ci = [FE.index(c) for c in cols]; mu, sd = Xtr[:, ci].mean(0), Xtr[:, ci].std(0) + 1e-6
        clf = LogisticRegression(C=1.0, max_iter=2000).fit((Xtr[:, ci] - mu) / sd, Ytr, sample_weight=wtr)
        sub = R[(R.d >= te0) & (R.d <= te1)]
        for (p, d), x in sub.groupby(["person_id", "d"]):
            idx, X = feats[(p, d)]; ph = dict(zip(idx, clf.predict_proba((X[:, ci] - mu) / sd)[:, 1]))
            R.loc[x.index, sn] = x.li.map(ph).to_numpy()
    print(name, "done", flush=True)

def boot(per_day, B=4000):
    v = np.asarray(per_day, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]

def person_metrics(s):
    out = {}; pd_ = R.groupby(["d", "person_id"])
    pos = pd_.y.transform("sum"); A = R[pos > 0].copy(); A["r"] = A.groupby(["d", "person_id"])[s].rank(ascending=False, method="first")
    h = A.groupby(["d", "person_id"]).apply(lambda g: pd.Series({"h1": float(g.y[g.r <= 1].sum() > 0), "h3": float(g.y[g.r <= 3].sum() > 0)}))
    hd = h.groupby(level=0).mean(); out["Hit@1"] = boot(hd.h1); out["Hit@3"] = boot(hd.h3)
    B_ = R[(pos > 0) & (pos < R.groupby(["d", "person_id"]).y.transform("size"))]
    au = B_.groupby(["d", "person_id"]).apply(lambda g: roc_auc_score(g.y, g[s])).groupby(level=0).mean(); out["within_lineup_AUC"] = boot(au)
    rp = []
    for d, x in R.groupby("d"):
        v = [g.nlargest(int(g.y.sum()), s).y.sum() / g.y.sum() for _, g in x.groupby("launch_id") if g.y.sum()]
        rp.append(np.mean(v))
    out["voter_R_precision"] = boot(rp)
    p = R[s].clip(1e-6, 1 - 1e-6); q = pd.qcut(p.rank(method="first"), 10, labels=False)
    tab = R.assign(q=q).groupby("q").agg(pred=(s, "mean"), real=("y", "mean"), n=("y", "size"))
    out["calibration_deciles [pred, real]"] = [[round(a, 5), round(b, 5)] for a, b in zip(tab.pred, tab.real)]
    out["ECE"] = round(float((tab.n * (tab.pred - tab.real).abs()).sum() / tab.n.sum()), 5); out["log_loss"] = round(log_loss(R.y, p), 5)
    pop = {}
    for k in (3, 5, 10):
        v = []
        for d, x in R.groupby("d"):
            ev = x.groupby("launch_id")[s].sum(); real = x.groupby("launch_id").y.sum()   # secondary: sample-sum EV vs sample votes
            v.append(len(set(ev.nlargest(k).index) & set(real.nlargest(k).index)) / k)
        pop[f"top{k}_vs_sample_votes"] = boot(v)
    out["population (secondary; vs the sample's own real votes)"] = pop
    return out

res = {"rows": int(len(R)), "days": int(R.d.nunique()), "person_days": int(R.groupby(["d", "person_id"]).ngroups), "model": "E5 logistic baseline, monthly (Sep model -> Oct days, Oct model -> Nov days)"}
for sn in SETS: res[sn] = person_metrics(sn)
d = (R.groupby(["d", "person_id"]).apply(lambda g: 0))  # placeholder to keep structure simple
R[["d", "person_id", "launch_id", "y"] + list(SETS)].to_parquet(W + "/out/usersim_ref_rows.parquet", index=False)
json.dump(res, open(W + "/out/usersim_ref_table.json", "w"), indent=1); print(json.dumps(res, indent=1))
