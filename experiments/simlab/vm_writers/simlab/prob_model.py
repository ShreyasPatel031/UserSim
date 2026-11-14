"""Per-launch probabilities for the two published predictions (orchestrator 01:20Z Nov 14). Counts only.
(1) 00:05 (arm 2 score, PH ops dump, Apr-Oct): for EVERY launch, P(top 3 / top 5 / top 10) from within-day position: rank by score,
    z-score within day, gap (z) to the launch above and below, log field size. Logistic per k, month-forward (score May-Oct); a day's
    probabilities are rescaled to sum to k (capped at 1, iterated). Baselines: base rate k/n; RANK TABLE = training share of launches at
    each rank (1..15, 16+ pooled) that finished top k, rescaled the same way. Metrics: reliability by decile, Brier and Brier skill vs base
    rate and vs rank table, all days and Sep-Oct.
(2) 03:45 (hybrid order on the 11 replay days, prereveal_345.py rebuild): rank-only table pooled over days, leave-one-day-out for the
    reported reliability / Brier; per-rank cells with day-bootstrap intervals (to show how wide they are).
(3) Frozen: reports/prob_model/frozen_prob_0005.json (logistic coefficients fit on all 214 days + feature recipe) and
    frozen_prob_prereveal.json (rank table from all 11 days).
    python prob_model.py <scratchpad> <out dir>
"""
import json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); KS = (3, 5, 10)
def feats(g, col):
    g = g.sort_values(col, ascending=False).copy(); s = g[col].values; z = (s - s.mean()) / (s.std() or 1)
    g["r"] = np.arange(1, len(g) + 1); g["z"] = z; g["gap_up"] = np.r_[0.0, z[:-1] - z[1:]] if len(z) > 1 else 0.0; g["gap_dn"] = np.r_[z[:-1] - z[1:], 0.0] if len(z) > 1 else 0.0
    g["lnr"] = np.log(g.r); g["lnn"] = np.log(len(g)); return g
FE = ["z", "lnr", "gap_up", "gap_dn", "lnn"]
def rescale(p, k):
    p = np.clip(np.asarray(p, float), 1e-6, 1)
    for _ in range(50):
        p = np.clip(p * k / p.sum(), 0, 1)
        if abs(p.sum() - k) < 1e-6: break
    return p
def rtable(T, k, col="r"): return {int(r): float(v) for r, v in T.assign(rb=T[col].clip(upper=16)).groupby("rb")[f"y{k}"].mean().items()}
X = pd.read_parquet(f"{SP}/a2x/X.parquet"); X["id"] = X.id.astype(str)
# day rule (orchestrator 12:45Z Nov 14): only days with >= 10 ranked launches, as the track record and the live scoreboard
_nr = X.groupby("day").dailyRank.apply(lambda s: s.notna().sum()); X = X[X.day.isin(_nr[_nr >= int(os.environ.get("MIN_RANKED", "10"))].index)].copy()
D = pd.concat([feats(g, "both") for _, g in X.groupby("day")]); D["mon"] = D.day.str[:7]
for k in KS: D[f"y{k}"] = (D.dailyRank <= k).astype(float)
for k in KS: D[f"p{k}"] = np.nan; D[f"t{k}"] = np.nan; D[f"b{k}"] = np.nan
mons = sorted(D.mon.unique())
for m in mons[1:]:
    tr, te = D[D.mon < m], D.mon == m
    for k in KS:
        lr = LogisticRegression(C=1.0, max_iter=1000).fit(tr[FE], tr[f"y{k}"]); D.loc[te, f"p{k}"] = lr.predict_proba(D.loc[te, FE])[:, 1]
        tb = rtable(tr, k); D.loc[te, f"t{k}"] = D.loc[te, "r"].clip(upper=16).map(tb).fillna(0.0)
for d, idx in D[D.mon > mons[0]].groupby("day").groups.items():
    n = len(idx)
    for k in KS:
        D.loc[idx, f"p{k}"] = rescale(D.loc[idx, f"p{k}"], min(k, n)); D.loc[idx, f"t{k}"] = rescale(D.loc[idx, f"t{k}"], min(k, n)); D.loc[idx, f"b{k}"] = min(k, n) / n
S = D[D.mon > mons[0]]
def evalset(S, name):
    o = {"days": int(S.day.nunique()), "launches": len(S)}
    for k in KS:
        y = S[f"y{k}"].values; p, t, b = S[f"p{k}"].values, S[f"t{k}"].values, S[f"b{k}"].values
        bp, bt, bb = np.mean((p - y) ** 2), np.mean((t - y) ** 2), np.mean((b - y) ** 2)
        dd = S.day.values; ud = np.unique(dd); ix = {d: np.flatnonzero(dd == d) for d in ud}; bs = []
        for _ in range(1000):
            j = np.concatenate([ix[d] for d in rng.choice(ud, len(ud))]); bs.append([1 - np.mean((p[j] - y[j]) ** 2) / np.mean((b[j] - y[j]) ** 2), 1 - np.mean((p[j] - y[j]) ** 2) / np.mean((t[j] - y[j]) ** 2)])
        bs = np.array(bs); bins = [0, .05, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.01]; cb = pd.cut(p, bins, right=False)
        rel = pd.DataFrame({"bin": cb, "p": p, "y": y}).groupby("bin", observed=True).agg(pred=("p", "mean"), obs=("y", "mean"), n=("y", "size"))
        o[f"top{k}"] = {"Brier model / rank table / base rate": [round(float(bp), 4), round(float(bt), 4), round(float(bb), 4)],
                        "Brier skill vs base rate [CI]": [round(float(1 - bp / bb), 3), round(float(np.percentile(bs[:, 0], 2.5)), 3), round(float(np.percentile(bs[:, 0], 97.5)), 3)],
                        "Brier skill vs rank table [CI]": [round(float(1 - bp / bt), 3), round(float(np.percentile(bs[:, 1], 2.5)), 3), round(float(np.percentile(bs[:, 1], 97.5)), 3)],
                        "reliability (bin: mean predicted %, observed %, n)": {str(i): [round(float(r.pred) * 100, 1), round(float(r.obs) * 100, 1), int(r.n)] for i, r in rel.iterrows()}}
    return o
res = {"design": __doc__.split("\n    python")[0], "(1) 00:05 all scored days (May-Oct)": evalset(S, "all"), "(1) 00:05 Sep-Oct": evalset(S[S.day >= "2026-09-01"], "sepoct")}
FZ = {"prediction": "00:05 PT", "basis": f"arm 2 walk-forward backtest, {X.day.min()} to {X.day.max()} ({X.day.nunique()} days with >= 10 ranked launches)", "features": FE,
      "recipe": "sort the day's launches by score desc; r = 1..n; z = within-day z of score; gap_up = z(prev) - z (0 for r=1); gap_dn = z - z(next) (0 for last); lnr = ln r; lnn = ln n; p_k = logistic(intercept + coef . features); rescale the day's p_k to sum to min(k, n) (cap 1, iterate)",
      "models": {}}
for k in KS:
    lr = LogisticRegression(C=1.0, max_iter=1000).fit(D[FE], D[f"y{k}"]); FZ["models"][f"top{k}"] = {"intercept": float(lr.intercept_[0]), "coef": dict(zip(FE, map(float, lr.coef_[0])))}
FZ["fallback rank table (no scores)"] = {f"top{k}": rtable(D, k) for k in KS}
json.dump(FZ, open(os.path.join(OUT, "frozen_prob_0005.json"), "w"), indent=1)
# (2) 03:45 replay: rebuild hybrid order (exec prereveal_345 up to the line families)
RES1, OUT0 = res, OUT; src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "prereveal_345.py")).read()
sys.argv = [sys.argv[0], SP, f"{SP}/a2x/nov_arm2.parquet", os.path.join(OUT, "_pr")]
exec(src[src.index("import glob, json, os, sys"):src.index("FAM = {")])
R = []
for d in DAYS:
    o = hybrid_order(D_ := globals()["D"][d], hrclean_w([x for x in DAYS if x != d]))
    for pos, i in enumerate(o, 1): R.append({"day": d, "id": i, "r": pos, **{f"y{k}": float(D_.loc[i, "rank"] <= k) for k in KS}})
res, OUT = RES1, OUT0; R = pd.DataFrame(R); o2 = {"days": len(DAYS), "launches": len(R)}
for k in KS:
    p = np.zeros(len(R))
    for d in DAYS:
        tb = rtable(R[R.day != d], k); m = (R.day == d).values; p[m] = rescale(R.loc[m, "r"].clip(upper=16).map(tb).fillna(0.0), min(k, m.sum()))
    y = R[f"y{k}"].values; b = np.array([min(k, (R.day == d).sum()) / (R.day == d).sum() for d in R.day])
    cells = {}
    for r in list(range(1, 11)) + [16]:
        sub = R[R.r.clip(upper=16) == r]; v = sub[f"y{k}"].values
        if len(v): bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]; cells[str(r) if r < 16 else "16+"] = [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
    o2[f"top{k}"] = {"LODO Brier rank table / base rate": [round(float(np.mean((p - y) ** 2)), 4), round(float(np.mean((b - y) ** 2)), 4)], "Brier skill vs base rate": round(float(1 - np.mean((p - y) ** 2) / np.mean((b - y) ** 2)), 3),
                     "pooled rank cells: % finishing top k [CI], n (positions 1-10, 16+ = 11+)": cells}
res["(2) 03:45 replay (hybrid order), rank-only table"] = o2
json.dump({"prediction": "03:45 PT", "basis": f"hybrid order on {len(DAYS)} replay days {DAYS[0]}..{DAYS[-1]}", "recipe": "position r in the published 03:45 order (1 = top pick; 11+ pooled as 16); p_k = table[r]; rescale the day to sum to min(k, n)",
           "table": {f"top{k}": {r_: round((v * (11 if r_ <= 10 else 194) + 0.5) / ((11 if r_ <= 10 else 194) + 1), 4) for r_, v in rtable(R.assign(r=R.r.clip(upper=11).replace(11, 16)), k).items()} for k in KS}}, open(os.path.join(OUT, "frozen_prob_prereveal.json"), "w"), indent=1)
json.dump(res, open(os.path.join(OUT, "prob_model.json"), "w"), indent=1, default=str)
for k, v in res.items():
    if k != "design": print(k, json.dumps(v, default=str)[:3000])
