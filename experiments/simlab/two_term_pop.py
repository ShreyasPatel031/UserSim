"""Two-term user simulation at population level (orchestrator Nov 11, (3)):
  logit P(p votes L) = logit P_taste(p, L) + a * z(LM_L)        (i) with the LM score as the 00:05 popularity term
  logit P(p votes L) = logit P_taste(p, L)                       (ii) taste only (no popularity)
P_taste = the E5 product-only logistic (unconditional, includes the person's activity), on the PH agent's 19-day rows.
LM_L = the honest out-of-sample base LM prediction from the lm_breakout harness (monthly folds), z-scored within day.
a is fitted by 2-fold cross-time (Oct days <-> Nov days): a for Nov days maximises the person log-likelihood on Oct days and
vice versa (a grid). EV_L = sum_p P. Daily top 3/5/10 vs real dailyRank, day bootstrap; references: LM alone, and the
quoted deployed sim (49.1/65.3/70.0) and arrivals-only (53.3/64.0/70.0) on the same 19 days.
    python two_term_pop.py <e5_ref_rows19.parquet> <lm_preds.parquet> <out.json>"""
import json, sys, numpy as np, pandas as pd
ROWS, LMP, OUT = sys.argv[1:4]; rng = np.random.default_rng(0)
R = pd.read_parquet(ROWS)[["d", "person_id", "launch_id", "y", "product_only"]]
LM = pd.read_parquet(LMP)[["id", "base", "day", "dailyRank"]].rename(columns={"id": "launch_id"}); LM["launch_id"] = LM.launch_id.astype(str)
LM["z"] = LM.groupby("day").base.transform(lambda s: (s - s.mean()) / (s.std() + 1e-9))
R = R.merge(LM[["launch_id", "z", "dailyRank"]], on="launch_id", how="left"); R = R[R.z.notna() & R.dailyRank.notna()].copy()
p = R.product_only.clip(1e-6, 1 - 1e-6).to_numpy(); lg = np.log(p / (1 - p)); y = R.y.to_numpy(); z = R.z.to_numpy()
nov = (R.d >= "2026-11-01").to_numpy()
grid = np.round(np.arange(0, 3.01, 0.1), 2)
def ll(a, m):
    q = 1 / (1 + np.exp(-(lg[m] + a * z[m]))); q = np.clip(q, 1e-9, 1 - 1e-9); return float(np.sum(y[m] * np.log(q) + (1 - y[m]) * np.log(1 - q)))
a_for_nov = grid[np.argmax([ll(a, ~nov) for a in grid])]; a_for_oct = grid[np.argmax([ll(a, nov) for a in grid])]
a = np.where(nov, a_for_nov, a_for_oct)
R["p_two"] = 1 / (1 + np.exp(-(lg + a * z))); R["p_taste"] = p
def topk(score):
    E = R.groupby(["d", "launch_id"]).agg(ev=(score, "sum"), rk=("dailyRank", "first")).reset_index()
    out = {}
    for k in (3, 5, 10):
        v = [len(set(g.nlargest(k, "ev").launch_id) & set(g.nsmallest(k, "rk").launch_id)) / k for _, g in E.groupby("d")]
        out[k] = np.array(v)
    return out
def boot(v, B=4000):
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(100 * float(v.mean()), 1), round(100 * float(np.percentile(bs, 2.5)), 1), round(100 * float(np.percentile(bs, 97.5)), 1)]
R["lm_only"] = R.z   # sum over people of a constant per launch = n_people * z: same order as z within a day
res = {"a_for_nov (fit on Oct)": float(a_for_nov), "a_for_oct (fit on Nov)": float(a_for_oct), "days": int(R.d.nunique()),
       "references (quoted, same 19 days)": {"deployed sim": [49.1, 65.3, 70.0], "arrivals-only": [53.3, 64.0, 70.0], "it8 full": [43.9, 63.2, 69.5]}}
T = {s: topk(s) for s in ("p_taste", "lm_only", "p_two")}
for s, t in T.items():
    res[s] = {f"top{k}": boot(t[k]) for k in (3, 5, 10)}
for s in ("p_two",):
    res[f"{s} minus lm_only (paired by day)"] = {f"top{k}": boot(T[s][k] - T["lm_only"][k]) for k in (3, 5, 10)}
    res[f"{s} minus p_taste (paired by day)"] = {f"top{k}": boot(T[s][k] - T["p_taste"][k]) for k in (3, 5, 10)}
from sklearn.metrics import roc_auc_score
for s in ("p_taste", "p_two"):
    res[s]["person log-loss"] = round(float(-np.mean(y * np.log(np.clip(R[s], 1e-9, 1)) + (1 - y) * np.log(np.clip(1 - R[s], 1e-9, 1)))), 5)
json.dump(res, open(OUT, "w"), indent=1); print(json.dumps(res, indent=1))
