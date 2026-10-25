"""Forward test: train on every finished day, predict today's launches (no votes used; results not final yet).
Writes results/forecast_<date>.md so it can be checked after the day closes (Pacific midnight)."""
import sys
import numpy as np, pandas as pd
import features as F, model as M, run as RN

import llm

day = sys.argv[1]
df0 = F.build(include_today=True)
for mode in ("pitch", "site", "brand"):  # same blind LLM judgements as the backtest rows get
    llm.run_day(day, df0[df0.day == day], mode)
df = RN.load_llm(df0)
df = df[~df.known]
tr, te = df[~df.is_today], df[df.is_today & (df.day == day)]
tr, te = M.add_fold_feats(tr, te)
te = te.copy()
te["pred"] = M.fit_predict(tr, te, M.SOURCES)[0]
te["rank_score"] = M.fit_rank(tr, te, M.SOURCES)
z = lambda v: (v - v.mean()) / (v.std() + 1e-9)
te["score"] = z(te.pred) + z(te.rank_score)
te = te.sort_values("score", ascending=False)
L = [f"# Forecast for {day} (made before results; {len(te)} featured launches at fetch time)\n",
     "| Predicted rank | Product | Tagline | Hunter PH followers |", "|---|---|---|---|"]
for i, (_, r) in enumerate(te.iterrows()):
    L.append(f"| {i + 1} | {r['name']} | {r.tagline} | {int(np.expm1(r.ph_hunter_followers))} |")
open(f"{RN.OUT}/forecast_{day}.md", "w").write("\n".join(L) + "\n")
import json, os
os.makedirs(f"{RN.OUT}/dash", exist_ok=True)
json.dump([{"rank": i + 1, "product": r["name"], "tagline": r.tagline, "hunter_followers": int(np.expm1(r.ph_hunter_followers)),
            "id": r.id} for i, (_, r) in enumerate(te.iterrows())], open(f"{RN.OUT}/dash/forecast.json", "w"))
print("\n".join(L))
