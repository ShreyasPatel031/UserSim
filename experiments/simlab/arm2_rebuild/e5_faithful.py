"""Explanation faithfulness audit (orchestrator 23:56Z Nov 14). 2026 test months 2026-04..2026-10, month-forward, train = rows of earlier months
from 2025-01-01, rows sorted by (day, id), same harness as e5_tiebreak / e5_makers0. Per launch:
  shown  = readable_v2 attributions as the site shows them (readable_shadow.py recipe: 10 inputs X10, LightGBM depth-1 stumps, 600 trees, lr 0.03,
           min_child_samples 40, subsample 0.8, monotone signs from a Ridge on day-z-scored inputs; pred_contrib averaged over 5 seeds)
  arm2   = arm 2 itself (deployed columns, TW.P0, 5 seeds) pred_contrib (TreeSHAP) averaged over seeds, GROUPED into the 10 readable inputs
           (a column belongs to input c if it is c or a within-day rank of c); every other arm-2 column -> "other (not in the readable model)"
Saved per launch: both attribution vectors. Scoring: score_faithful.py.      usage: python e5_faithful.py <out parquet>"""
import json, os, sys, time
os.environ.setdefault("LGB_THREADS", "4")
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.linear_model import Ridge
import history_retrain as HR, training_window as TW
t0 = time.time(); OUT = sys.argv[1]; SEEDS = range(5)
X10 = ["hist_hunter_rel", "hist_hunter_n", "hist_hunter_top5", "llm_pitch", "topic_prior_mean", "txt_ridge", "ph_n_media", "ph_n_makers", "ph_hunter_age_d", "promo_cov"]
df, _ = HR.build(os.environ["H25_SRC"]); X = df.reset_index(drop=True); X["id"] = X.id.astype(str); X = X.sort_values(["day", "id"]).reset_index(drop=True)
P = dict(TW.P0, n_jobs=int(os.environ["LGB_THREADS"]))
def group(c):
    for x in X10:
        if c == x or (("dayrank" in c) and c.endswith(x)): return x
    return "other"
def zday(D):
    Z = D[["day"] + X10].copy()
    for c in X10:
        g = Z.groupby("day")[c]; Z[c] = ((Z[c] - g.transform("mean")) / g.transform("std").replace(0, np.nan)).fillna(0.0)
    return Z[X10]
rows = []
for m in [f"2026-{k:02d}" for k in range(4, 11)]:
    te0 = X[X.mon == m]; tr0 = X[(X.mon < m) & (X.day >= "2025-01-01")]
    tr, te, cols = TW.prep(tr0, te0); base = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    tr, te = tr.sort_values(["day", "id"]), te.sort_values(["day", "id"])
    # arm 2 SHAP
    C2 = np.zeros((len(te), len(base))); pred2 = np.zeros(len(te))
    for s in SEEDS:
        mdl = lgb.LGBMRegressor(random_state=s, **P).fit(tr[base], tr.logv); pc = mdl.predict(te[base], pred_contrib=True)
        C2 += pc[:, :len(base)] / len(SEEDS); pred2 += mdl.predict(te[base]) / len(SEEDS)
    G = pd.DataFrame(C2, columns=base).T.groupby([group(c) for c in base]).sum().T
    # readable_v2 (readable_shadow.py recipe)
    sign = np.where(Ridge(alpha=3.0).fit(zday(tr), tr.logv).coef_ >= 0, 1, -1).astype(int)
    CR = np.zeros((len(te), len(X10))); predr = np.zeros(len(te))
    for s in SEEDS:
        g_ = lgb.LGBMRegressor(n_estimators=600, learning_rate=0.03, num_leaves=2, min_child_samples=40, subsample=0.8, subsample_freq=1,
                               monotone_constraints=list(sign), random_state=s, verbose=-1, n_jobs=int(os.environ["LGB_THREADS"])).fit(tr[X10], tr.logv)
        pc = g_.predict(te[X10], pred_contrib=True); CR += pc[:, :len(X10)] / len(SEEDS); predr += g_.predict(te[X10]) / len(SEEDS)
    o = te[["id", "day", "dailyRank"]].copy().reset_index(drop=True); o["pred_arm2"] = pred2; o["pred_readable"] = predr
    for c in X10: o[f"r_{c}"] = CR[:, X10.index(c)]; o[f"a_{c}"] = G[c].values if c in G else 0.0
    o["a_other"] = G["other"].values if "other" in G else 0.0
    for c in X10: o[f"v_{c}"] = te[c].values   # raw input values (for the site)
    rows.append(o); print(json.dumps({"month": m, "n_test": len(te), "arm2_cols": len(base), "other_cols": int(sum(group(c) == "other" for c in base)), "s": round(time.time() - t0)}), flush=True)
pd.concat(rows).to_parquet(OUT); print("done", flush=True)
