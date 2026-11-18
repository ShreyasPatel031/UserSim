"""Forward test: train on every finished day, predict today's launches (no votes used; results not final yet).
Writes results/forecast_<date>.md so it can be checked after the day closes (Pacific midnight)."""
import os, sys
import numpy as np, pandas as pd
import features as F, model as M, run as RN

import llm

day = sys.argv[1]
df0 = F.build(include_today=True)
for mode in ("pitch", "site", "brand", "full"):  # same blind LLM judgements as the backtest rows get
    llm.run_day(day, df0[df0.day == day], mode)
df = RN.load_llm(df0)
df = df[~df.known]
tr, te = df[~df.is_today], df[df.is_today & (df.day == day)]
tr, te = M.add_fold_feats(tr, te)
te = te.copy()
src, dropped = M.live_sources(tr, te, M.LIVE_SOURCES)
print("sources", src, "dropped (empty today, filled in training):", dropped, flush=True)
# the configuration the backtest scores (liveexp.py / pipeline.backtest), averaged over 5 seeds (+0.6 daily top 3)
# DEPLOY candidate clean_nosite (orchestrator 14:40Z Nov 12): the 00:05 model trained and served without any input that
# needs a NAMED maker (maker profiles, ID set) and without llm_site; published order = this clean score. Backtest 214 days
# 56.4 / 67.8 / 75.0; as-live 15 days 29/45 top-3 hits, #1 in top 3 14/15 (deployed 27/45, 8/15). No new data dependency.
import lightgbm as lgb
MP = ("ph_maker", "hist_maker", "hist_dayrank_hist_maker", "x_maker", "x_n_makers")
ID = {"ph_n_makers_new", "ph_maker_has_headline", "x_any_verified", "ph_self_hunted"}
cc = [c for c in M.cols(tr, src) if not c.startswith(MP) and c not in ID and c != "llm_site"]
P_ = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
          colsample_bytree=0.5, reg_lambda=1.0)   # = makerfix_shadow's clean line / training_window P0
te["pred"] = np.mean([lgb.LGBMRegressor(random_state=s, verbose=-1, n_jobs=M.N_JOBS, **P_).fit(tr[cc], tr.logv).predict(te[cc])
                      for s in range(5)], axis=0)
te["score"] = te.pred
# PUBLISHED 00:05 ORDER = arm 2 (Shreyas, direct, Nov 13 ~19:10Z: "if its better on backtest deploy"; orchestrator call 19:06Z):
# 2025-trained clean_nosite with Gemini pitch/brand on 2025 rows (h25_live.py; 214 days top 3 60.7 vs 56.9, +3.9 [+1.4, +6.5]).
# te.pred stays the clean_nosite prediction (the log-vote prior every downstream line reads from forecast_<day>.parquet);
# pred_arm2 is added; if arm 2 fails, the published order falls back to clean_nosite and the log says so.
te["pred_arm2"] = np.nan; ARM2 = "fallback: clean_nosite"
try:
    sys.path.insert(0, os.path.expanduser("~/w/arm2_live")); import h25_live   # pinned copies (h25_live.py, history_retrain.py), not the experiment dir
    PA, info = h25_live.predict(day); te["pred_arm2"] = te.id.astype(str).map(dict(zip(PA.id, PA.pred_arm2)))
    if te.pred_arm2.notna().all():
        te["score"] = te.pred_arm2; ARM2 = f"arm2 published ({info})"
    else:
        ARM2 = f"fallback: clean_nosite (arm2 missing for {int(te.pred_arm2.isna().sum())} launches)"
except Exception as e:
    ARM2 = f"fallback: clean_nosite (arm2 error {type(e).__name__}: {str(e)[:160]})"
# ARM 3 PUBLISH SWITCH (bundle 13, undeployed): only when ~/w/arm3_live/PUBLISH exists (created by deploy_arm3.sh publish, on Shreyas's
# direct word). Then the published 00:05 order = pred_arm3 (E5 arm3_live, pinned bge-small, offline); arm 2 stays in the parquet as the
# shadow column pred_arm2. Any arm-3 failure keeps the arm-2 (or clean_nosite) order and says why. Without the file nothing changes.
te["pred_arm3"] = np.nan; ARM3 = "off (no PUBLISH file)"
if os.path.exists(os.path.expanduser("~/w/arm3_live/PUBLISH")):
    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "1"); os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        sys.path.insert(0, os.path.expanduser("~/w/arm3_live")); import arm3_live
        PB, info3 = arm3_live.predict(day); te["pred_arm3"] = te.id.astype(str).map(dict(zip(PB.id, PB.pred_arm3)))
        if te.pred_arm3.notna().all():
            te["score"] = te.pred_arm3; ARM3 = f"arm3 published ({info3}); arm 2 kept as shadow"
        else:
            te["pred_arm3"] = np.nan; ARM3 = f"arm3 missing for some launches: kept {ARM2}"
    except Exception as e:
        te["pred_arm3"] = np.nan; ARM3 = f"arm3 error {type(e).__name__}: {str(e)[:160]}: kept {ARM2}"
print("published model:", ARM3 if ARM3.startswith("arm3 published") else ARM2, "| arm3:", ARM3, flush=True)
te = te.sort_values("score", ascending=False)
L = [f"# Forecast for {day} (made before results; {len(te)} featured launches at fetch time)\n",
     "| Predicted rank | Product | Tagline | Hunter PH followers |", "|---|---|---|---|"]
for i, (_, r) in enumerate(te.iterrows()):
    L.append(f"| {i + 1} | {r['name']} | {r.tagline} | {int(np.expm1(r.ph_hunter_followers))} |")
open(f"{RN.OUT}/forecast_{day}.md", "w").write("\n".join(L) + "\n")
# the launch model's raw prediction (log votes) per launch: the offset for shadow forecasts (pipeline.daily s_shadow)
AUD = ["ph_hunter_followers", "x_maker_sum_followers", "x_company_followers", "promo_reactions", "promo_posts"]   # E1 v2's audience inputs
te[["id", "day", "pred", "pred_arm2"] + (["pred_arm3"] if te.pred_arm3.notna().any() else []) + [c for c in AUD if c in te]].assign(id=te.id.astype(str)).to_parquet(f"{RN.OUT}/forecast_{day}.parquet")
import json, os
os.makedirs(f"{RN.OUT}/dash", exist_ok=True)
json.dump([{"rank": i + 1, "product": r["name"], "tagline": r.tagline, "hunter_followers": int(np.expm1(r.ph_hunter_followers)),
            "id": r.id} for i, (_, r) in enumerate(te.iterrows())], open(f"{RN.OUT}/dash/forecast.json", "w"))
print("\n".join(L))
