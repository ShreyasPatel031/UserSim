"""Person-level check of the two-term user sim (orchestrator 09:40Z Nov 11, (3)): does taste add anything to the LM at the
PERSON level? On the PH 19-day rows:
  POP   logit P = logit(activity_p) + a*z(LM_L): the person's own base rate (mean P_taste over that day's line-up) plus
        LM popularity - no person-specific taste over launches
  TWO   logit P = logit P_taste(p, L) + a*z(LM_L)
  TWOsh TWO with the taste row of a random other person on the same day (shuffled control)
a cross-time fitted per model (Oct <-> Nov), as two_term_pop.py. Metrics: person log-loss (all rows), within-line-up Hit@1,
Hit@3, AUC on voting person-days; day bootstrap; paired TWO-POP and TWO-TWOsh.
    python two_term_person.py <e5_ref_rows19.parquet> <lm_preds.parquet> <out.json>"""
import json, sys, numpy as np, pandas as pd
ROWS, LMP, OUT = sys.argv[1:4]; rng = np.random.default_rng(0)
R = pd.read_parquet(ROWS)[["d", "person_id", "launch_id", "y", "product_only"]]
LM = pd.read_parquet(LMP)[["id", "base", "day"]].rename(columns={"id": "launch_id"}); LM["launch_id"] = LM.launch_id.astype(str)
LM["z"] = LM.groupby("day").base.transform(lambda s: (s - s.mean()) / (s.std() + 1e-9))
R = R.merge(LM[["launch_id", "z"]], on="launch_id", how="left"); R = R[R.z.notna()].sort_values(["d", "person_id", "launch_id"]).reset_index(drop=True)
lg = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
R["act"] = R.groupby(["d", "person_id"]).product_only.transform("mean")
# shuffled taste: within each day, give person p the taste vector of another person (same line-up order)
R["taste_sh"] = np.nan
for d, g in R.groupby("d"):
    ps = g.person_id.unique(); perm = dict(zip(ps, rng.permutation(ps)))
    piv = g.pivot_table(index="person_id", columns="launch_id", values="product_only")
    R.loc[g.index, "taste_sh"] = [piv.at[perm[p], l] for p, l in zip(g.person_id, g.launch_id)]
base = {"POP": lg(R.act.to_numpy()), "TWO": lg(R.product_only.to_numpy()), "TWOsh": lg(R.taste_sh.to_numpy())}
y = R.y.to_numpy(); z = R.z.to_numpy(); nov = (R.d >= "2026-11-01").to_numpy(); grid = np.round(np.arange(0, 3.01, 0.1), 2)
def ll(b, a, m):
    q = np.clip(1 / (1 + np.exp(-(b[m] + a * z[m]))), 1e-9, 1 - 1e-9); return float(np.sum(y[m] * np.log(q) + (1 - y[m]) * np.log(1 - q)))
fit = {}
for k, b in base.items():
    an = grid[np.argmax([ll(b, a, ~nov) for a in grid])]; ao = grid[np.argmax([ll(b, a, nov) for a in grid])]
    R[k] = 1 / (1 + np.exp(-(b + np.where(nov, an, ao) * z))); fit[k] = {"a_for_nov": float(an), "a_for_oct": float(ao)}
def per_day(s):
    D = R[R.groupby(["d", "person_id"]).y.transform("sum") > 0].copy(); D["v"] = D[s] + rng.random(len(D)) * 1e-12
    D["r"] = D.groupby(["d", "person_id"]).v.rank(ascending=False, method="first")
    h = D.groupby(["d", "person_id"]).apply(lambda g: pd.Series({"h1": float(g.y[g.r <= 1].sum() > 0), "h3": float(g.y[g.r <= 3].sum() > 0),
        "auc": np.mean(g.v[g.y == 1].to_numpy()[:, None] > g.v[g.y == 0].to_numpy()[None, :]) if (g.y == 0).any() else np.nan}))
    out = h.groupby(level=0).mean()
    q = np.clip(R[s], 1e-9, 1 - 1e-9); out["logloss"] = (-(R.y * np.log(q) + (1 - R.y) * np.log(1 - q))).groupby(R.d).mean()
    return out
def boot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 5), round(float(np.percentile(bs, 2.5)), 5), round(float(np.percentile(bs, 97.5)), 5)]
T = {k: per_day(k) for k in ("POP", "TWO", "TWOsh")}
res = {"fit_a": fit, "rows": int(len(R)), "days": int(R.d.nunique())}
for k, t in T.items(): res[k] = {m: boot(t[m]) for m in ("h1", "h3", "auc", "logloss")}
res["TWO - POP (paired by day)"] = {m: boot(T["TWO"][m] - T["POP"][m]) for m in ("h1", "h3", "auc", "logloss")}
res["TWO - TWOsh (personal)"] = {m: boot(T["TWO"][m] - T["TWOsh"][m]) for m in ("h1", "h3", "auc", "logloss")}
json.dump(res, open(OUT, "w"), indent=1); print(json.dumps(res, indent=1))
