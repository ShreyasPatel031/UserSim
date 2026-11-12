"""Forward test: train on every finished day, predict today's launches (no votes used; results not final yet).
Writes results/forecast_<date>.md so it can be checked after the day closes (Pacific midnight)."""
import sys
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
te = te.sort_values("score", ascending=False)
L = [f"# Forecast for {day} (made before results; {len(te)} featured launches at fetch time)\n",
     "| Predicted rank | Product | Tagline | Hunter PH followers |", "|---|---|---|---|"]
for i, (_, r) in enumerate(te.iterrows()):
    L.append(f"| {i + 1} | {r['name']} | {r.tagline} | {int(np.expm1(r.ph_hunter_followers))} |")
open(f"{RN.OUT}/forecast_{day}.md", "w").write("\n".join(L) + "\n")
# the launch model's raw prediction (log votes) per launch: the offset for shadow forecasts (pipeline.daily s_shadow)
AUD = ["ph_hunter_followers", "x_maker_sum_followers", "x_company_followers", "promo_reactions", "promo_posts"]   # E1 v2's audience inputs
te[["id", "day", "pred"] + [c for c in AUD if c in te]].assign(id=te.id.astype(str)).to_parquet(f"{RN.OUT}/forecast_{day}.parquet")
import json, os
os.makedirs(f"{RN.OUT}/dash", exist_ok=True)
json.dump([{"rank": i + 1, "product": r["name"], "tagline": r.tagline, "hunter_followers": int(np.expm1(r.ph_hunter_followers)),
            "id": r.id} for i, (_, r) in enumerate(te.iterrows())], open(f"{RN.OUT}/dash/forecast.json", "w"))
print("\n".join(L))
