"""Readable 00:05 model vs clean_nosite (orchestrator 17:40Z Nov 13, model-selection rule in AGENTS.md). Runs on the pipeline VM
(features build), outside 00:05-01:00 PT. 10 named inputs, all in the deployed clean_nosite input set (known at 00:05):
  hist_hunter_rel, hist_hunter_n (hunter track record), llm_pitch, llm_brand (Gemini pitch / brand), topic_prior_mean (topic prior),
  comp_nn_max (closest same-day competitor similarity), ph_n_media, ph_has_video (media), ph_n_makers (team size), promo_cov (pre-launch promotion).
Walk-forward by month exactly as history_retrain (train on months < m, test month m, Apr-Oct 2026).
  (a) ridge on within-day z-scores (missing -> 0 after z), one weight per input
  (b) additive monotone GBM: LightGBM, num_leaves=2 (stumps, so the score is a sum of per-input step functions), monotone sign per
      input from that month's training-data ridge sign (no future data), 5 seeds; per-launch contributions = pred_contrib summed per input
Output: results/readable_preds.parquet (id, day, a, b) + results/readable_contrib.parquet (id, input, points; model b, seed 0)."""
import json, os, sys, time
import numpy as np, pandas as pd
import features as F, run as RN, training_window as TW
from sklearn.linear_model import Ridge
import lightgbm as lgb
X10 = ["hist_hunter_rel", "hist_hunter_n", "llm_pitch", "llm_brand", "topic_prior_mean", "comp_nn_max", "ph_n_media", "ph_has_video", "ph_n_makers", "promo_cov"]
# READABLE_SET=v2: drops the three near-zero stumps of v1 (llm_brand, ph_has_video, comp_nn_max: mean |points| <= 0.005) for the text-model
# score, the hunter's past top-5 count and hunter account age; outputs get the _v2 suffix
SET = os.environ.get("READABLE_SET", "v1"); SUF = "" if SET == "v1" else "_" + SET
if SET == "v2":
    X10 = ["hist_hunter_rel", "hist_hunter_n", "hist_hunter_top5", "llm_pitch", "topic_prior_mean", "txt_ridge", "ph_n_media", "ph_n_makers", "ph_hunter_age_d", "promo_cov"]
MONTHS = [m for m in TW.MONTHS if "2026-04" <= m <= "2026-10"]


def zday(D):
    Z = D[["day"] + X10].copy()
    for c in X10:
        g = Z.groupby("day")[c]; Z[c] = ((Z[c] - g.transform("mean")) / g.transform("std").replace(0, np.nan)).fillna(0.0)
    return Z[X10]


def main():
    t0 = time.time(); df = RN.load_llm(F.build()); df = df[~df.known].copy(); df["mon"] = df.day.str[:7]
    df["y"] = df.logv
    out, contrib, signs = [], [], {}
    for m in MONTHS:
        tr0, te0 = df[df.mon < m], df[df.mon == m]
        if te0.empty: continue
        tr, te, _ = TW.prep(tr0, te0)   # fold features (topic priors, competitor similarity) built from the training months only, as clean_nosite
        tr = tr.assign(y=tr.logv)
        rz = Ridge(alpha=3.0).fit(zday(tr), tr.y); sign = np.where(rz.coef_ >= 0, 1, -1).astype(int); signs[m] = dict(zip(X10, map(int, sign)))
        a = rz.predict(zday(te))
        bs = []
        for s in range(5):
            g = lgb.LGBMRegressor(n_estimators=600, learning_rate=0.03, num_leaves=2, min_child_samples=40, subsample=0.8, subsample_freq=1,
                                  monotone_constraints=list(sign), random_state=s, verbose=-1, n_jobs=4).fit(tr[X10], tr.y)
            bs.append(g.predict(te[X10]))
            if s == 0:
                pc = g.predict(te[X10], pred_contrib=True)
                for k, c in enumerate(X10):
                    contrib.append(pd.DataFrame({"id": te.id.astype(str).values, "input": c, "points": pc[:, k]}))
        out.append(pd.DataFrame({"id": te.id.astype(str).values, "day": te.day.values, "a": a, "b": np.mean(bs, 0)}))
        print(json.dumps({"month": m, "seconds": round(time.time() - t0)}), flush=True)
    pd.concat(out).to_parquet(f"results/readable_preds{SUF}.parquet"); pd.concat(contrib).to_parquet(f"results/readable_contrib{SUF}.parquet")
    json.dump(signs, open(f"results/readable_signs{SUF}.json", "w"), indent=1)
    print(json.dumps({"signs_last_month": signs[max(signs)], "rows": int(sum(len(o) for o in out))}))


if __name__ == "__main__":
    main()
