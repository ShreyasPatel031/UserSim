"""Nightly shadow line + forecast-side why drivers: readable v2 stumps (orchestrator 18:46Z Nov 13; readable_model_v2.md: input set fixed on the
first 107 days; (b)+th_n_pre vs clean_nosite+th_n_pre -1.2 [-3.4, +0.9] top 3 on all 214 days, not worse). Runs on the pipeline VM after
01:00 PT (never 00:05-01:00 PT), read-only for everything deployed. Training: all days < d of the plain 2026 build, today's 00:05 rows
(data/today/<d>.json); fold features via TW.prep; LightGBM stumps (num_leaves=2), monotone signs from the training-data ridge, 5 seeds.
Output results/shadow_readable/<d>.json: per launch pred_readable_v2, rank, and the per-input points (sum of the stumps on that input,
seed mean; points add up to pred minus the base value). usage (VM, from ph_predict): PYTHONPATH=~/w/mk:. python3 ~/w/h25/readable_shadow.py <d>"""
import json, os, sys
import numpy as np, pandas as pd
import features as F, run as RN, training_window as TW
from sklearn.linear_model import Ridge
import lightgbm as lgb
X10 = ["hist_hunter_rel", "hist_hunter_n", "hist_hunter_top5", "llm_pitch", "topic_prior_mean", "txt_ridge", "ph_n_media", "ph_n_makers", "ph_hunter_age_d", "promo_cov"]
LABEL = {"hist_hunter_rel": "hunter track record (relative)", "hist_hunter_n": "hunter launches before", "hist_hunter_top5": "hunter top-5 finishes before",
         "llm_pitch": "Gemini pitch score", "topic_prior_mean": "topic prior", "txt_ridge": "text model score", "ph_n_media": "media items",
         "ph_n_makers": "team size", "ph_hunter_age_d": "hunter account age", "promo_cov": "pre-launch promotion"}


def zday(D):
    Z = D[["day"] + X10].copy()
    for c in X10:
        g = Z.groupby("day")[c]; Z[c] = ((Z[c] - g.transform("mean")) / g.transform("std").replace(0, np.nan)).fillna(0.0)
    return Z[X10]


def main(d):
    now = pd.Timestamp.now(tz="America/Los_Angeles")
    if now.strftime("%Y-%m-%d") == d and now.hour < 1:
        print(json.dumps({"day": d, "status": "before 01:00 PT; not running"})); return
    df = RN.load_llm(F.build(include_today=True)); df["id"] = df.id.astype(str)
    tr0 = df[(~df.is_today) & (df.day < d) & (~df.known)]; te0 = df[df.is_today & (df.day == d) & (~df.known)]
    if te0.empty:
        print(json.dumps({"day": d, "status": "no 00:05 rows"})); return
    tr, te, _ = TW.prep(tr0, te0)
    sign = np.where(Ridge(alpha=3.0).fit(zday(tr), tr.logv).coef_ >= 0, 1, -1).astype(int)
    P, C, base = [], np.zeros((len(te), len(X10))), []
    for s in range(5):
        g = lgb.LGBMRegressor(n_estimators=600, learning_rate=0.03, num_leaves=2, min_child_samples=40, subsample=0.8, subsample_freq=1,
                              monotone_constraints=list(sign), random_state=s, verbose=-1, n_jobs=4).fit(tr[X10], tr.logv)
        P.append(g.predict(te[X10])); pc = g.predict(te[X10], pred_contrib=True); C += pc[:, :len(X10)] / 5; base.append(pc[:, -1].mean())
    out = pd.DataFrame({"id": te.id.values, "pred_readable_v2": np.mean(P, 0)}); out["rank_readable_v2"] = out.pred_readable_v2.rank(ascending=False, method="first").astype(int)
    out["points"] = [dict(zip(X10, map(lambda v: round(float(v), 4), row))) for row in C]
    res = {"day": d, "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "model": "readable v2: additive monotone stumps, 10 inputs (readable_model_v2.md)",
           "inputs": "data/today/<d>.json (00:05 snapshot) only", "labels": LABEL, "signs": dict(zip(X10, map(int, sign))), "base_value": round(float(np.mean(base)), 4),
           "train_days": int(tr.day.nunique()), "launches": int(len(out)), "accuracy_backtest": "214 days Apr-Oct: alone 54.4 / 66.8 / 74.5; + th_n_pre 58.9 / 69.2 / 74.5 (top 3/5/10)",
           "forecast": out.sort_values("rank_readable_v2").to_dict("records")}
    os.makedirs(f"{RN.OUT}/shadow_readable", exist_ok=True); p = f"{RN.OUT}/shadow_readable/{d}.json"; json.dump(res, open(p, "w"), indent=1); print(p)


if __name__ == "__main__":
    main(sys.argv[1])
