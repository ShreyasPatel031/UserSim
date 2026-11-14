"""Forward test: train on every finished day, predict today's launches (no votes used; results not final yet).
Writes results/forecast_<date>.md so it can be checked after the day closes (Pacific midnight)."""
import os, sys
import numpy as np, pandas as pd
import features as F, model as M, run as RN

import llm

day = sys.argv[1]
import input_guard as G   # input guards (bundle 13): store freshness, llm coverage with retry, promo/busy/site alerts
G.store_check(day)        # may point F.D at an overlay store with missing days restored from the bucket (never writes the real store)
df0 = F.build(include_today=day)   # TODAY-ROWS callers: this day's line-up only (data/today/<day>.json), never the newest other file
if not (df0.is_today & (df0.day == day)).any():   # no line-up for this day: stop; no forecast_<day> file, so the 00:05 writer reports none_available
    sys.exit(f"no line-up for {day}: data/today/{day}.json missing or empty")
for mode in ("pitch", "site", "brand", "full"):  # same blind LLM judgements as the backtest rows get
    llm.run_day(day, df0[df0.day == day], mode)
G.llm_check(day, df0[df0.day == day])   # pitch/brand for every launch: re-score the missing subset with backoff, record the rest
df = RN.load_llm(df0)
# KNOWN LAUNCHES (bug sweep 1): dropped from TRAINING only; tonight's known launches stay in the line-up with every llm_* input blank
KNOWN = set(df.id[df.known & df.is_today & (df.day == day)].astype(str))
df = df[~df.known | (df.is_today & (df.day == day))]
tr, te = df[~df.is_today], df[df.is_today & (df.day == day)].copy()
te.loc[te.id.astype(str).isin(KNOWN), [c for c in te.columns if c.startswith("llm_")]] = np.nan
tr, te = M.add_fold_feats(tr, te)
te = te.copy()
src, dropped = M.live_sources(tr, te, M.LIVE_SOURCES)
print("sources", src, "dropped (empty today, filled in training):", dropped, flush=True)
G.coverage(te); G.STATE["dropped_sources"] = dropped
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
# REPRODUCIBILITY: (day, id) row order, deterministic row-wise LightGBM, fixed threads, 5 seeds (20 tested, no gain); input sha256 + versions
# -> results/forecast_repro_<day>.json (an audit rerun on the same snapshot is bit-identical)
import hashlib, json as _json
RS = int(os.environ.get("REPRO_SEEDS", "5")); RJ = int(os.environ.get("REPRO_JOBS", "4"))
tr = tr.sort_values(["day", "id"], kind="stable"); te = te.sort_values(["day", "id"], kind="stable")
_sha = lambda X: hashlib.sha256(pd.util.hash_pandas_object(X, index=False).values.tobytes()).hexdigest()[:16]
te["pred"] = np.mean([lgb.LGBMRegressor(random_state=s, verbose=-1, deterministic=True, force_row_wise=True, n_jobs=RJ, **P_).fit(tr[cc], tr.logv).predict(te[cc])
                      for s in range(RS)], axis=0)
REPRO = {"clean_nosite": {"seeds": RS, "sha_train": _sha(tr[cc + ["logv"]]), "sha_test": _sha(te[["id"] + cc]), "inputs": len(cc)},
         "versions": {"lightgbm": lgb.__version__, "numpy": np.__version__, "pandas": pd.__version__}}
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
# ARM 3 PUBLISH SWITCH (live-code 2, undeployed): only when ~/w/arm3_live/PUBLISH exists (deploy_arm3.sh publish, on Shreyas's direct word).
# Then the published 00:05 order = pred_arm3 (E5 arm3_live, pinned bge-small, offline); arm 2 stays in the parquet as the shadow pred_arm2.
# Any arm-3 failure keeps the arm-2 (or clean_nosite) order, and the published model then says so: "arm2 (arm3 failed: ...)".
te["pred_arm3"] = np.nan; ARM3 = "off (no PUBLISH file)"; PUB_ON = os.path.exists(os.path.expanduser("~/w/arm3_live/PUBLISH"))
if PUB_ON:
    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "1"); os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        sys.path.insert(0, os.path.expanduser("~/w/arm3_live")); import arm3_live
        PB, info3 = arm3_live.predict(day); te["pred_arm3"] = te.id.astype(str).map(dict(zip(PB.id, PB.pred_arm3)))
        if te.pred_arm3.notna().all():
            te["score"] = te.pred_arm3; ARM3 = f"arm3 published ({info3}); arm 2 kept as shadow"
        else:
            te["pred_arm3"] = np.nan; ARM3 = f"arm3 missing for some launches"
    except Exception as e:
        te["pred_arm3"] = np.nan; ARM3 = f"arm3 error {type(e).__name__}: {str(e)[:160]}"
# the ONE published-model name (forecast parquet column published_model, repro json, guard record, log): arm3 / arm2 / clean_nosite,
# with the arm-3 failure named when PUBLISH was on (bug fixes 1 and 3, E5 arm-3 pre-publish audit)
if ARM3.startswith("arm3 published"): PUBLISHED = "arm3"
elif ARM2.startswith("arm2 published"): PUBLISHED = "arm2" if not PUB_ON else f"arm2 (arm3 failed: {ARM3[:120]})"
else: PUBLISHED = "clean_nosite" if not PUB_ON else f"clean_nosite (arm3 failed: {ARM3[:80]}; {ARM2[:80]})"
print("published model:", PUBLISHED, "|", ARM2, "| arm3:", ARM3, flush=True)
G.STATE["published_model"] = PUBLISHED; print("input guard:", G.finish(day, RN.OUT), flush=True)
REPRO["arm2"] = {k: v for k, v in (info.items() if "info" in dir() and isinstance(info, dict) else []) if k in ("seeds", "sha_train", "sha_test", "versions", "inputs")}
REPRO["published"] = PUBLISHED; REPRO["arm2_status"] = ARM2; REPRO["arm3_status"] = ARM3; REPRO["known_in_lineup"] = len(KNOWN); _json.dump(REPRO, open(f"{RN.OUT}/forecast_repro_{day}.json", "w"), indent=1)
te = te.sort_values("score", ascending=False)
L = [f"# Forecast for {day} (made before results; {len(te)} featured launches at fetch time)\n",
     "| Predicted rank | Product | Tagline | Hunter PH followers |", "|---|---|---|---|"]
for i, (_, r) in enumerate(te.iterrows()):
    L.append(f"| {i + 1} | {r['name']}{' (known to the LLM; ranked without LLM inputs)' if str(r.id) in KNOWN else ''} | {r.tagline} | {int(np.expm1(r.ph_hunter_followers))} |")
open(f"{RN.OUT}/forecast_{day}.md", "w").write("\n".join(L) + "\n")
# the launch model's raw prediction (log votes) per launch: the offset for shadow forecasts (pipeline.daily s_shadow)
AUD = ["ph_hunter_followers", "x_maker_sum_followers", "x_company_followers", "promo_reactions", "promo_posts"]   # E1 v2's audience inputs
# published_rank + known (bug sweep 4: daily.py writes the forecasts table from these ids, not from names in the .md)
te[["id", "day", "pred", "pred_arm2"] + (["pred_arm3"] if te.pred_arm3.notna().any() else []) + [c for c in AUD if c in te]].assign(
    id=te.id.astype(str), published_rank=np.arange(1, len(te) + 1), known=te.id.astype(str).isin(KNOWN),
    published_model=PUBLISHED).to_parquet(f"{RN.OUT}/forecast_{day}.parquet")
import json, os
os.makedirs(f"{RN.OUT}/dash", exist_ok=True)
json.dump([{"rank": i + 1, "product": r["name"], "tagline": r.tagline, "hunter_followers": int(np.expm1(r.ph_hunter_followers)),
            "id": r.id} for i, (_, r) in enumerate(te.iterrows())], open(f"{RN.OUT}/dash/forecast.json", "w"))
print("\n".join(L))
