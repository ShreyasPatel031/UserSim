"""Known-launch audit (orchestrator bug sweep item 1, 18:35Z Nov 14). Read-only; counts only.
Gemini's "known" flag (run.load_llm: the LLM says it remembers the launch) drops a launch from test rows in the backtest and from tonight's
line-up in forecast.py / h25_live.py. Here: per labelled day, how many launches are known and where they finished; and the backtest
(results/history_retrain_decomp_preds_arm2.parquet 'both' = arm 2, 'pure' = clean_nosite-style) scored three ways:
  (a) known launches excluded from the truth (as the backtest does now: truth = ranked test rows)
  (b) known launches kept in the truth, never predicted (each one in the true top k is a miss) - what the live scoreboard already does
  (c) known launches kept and ranked: needs a refit with known rows in the test set (separate run)
usage (VM, cwd ~/w/experiments/ph_predict): python3 known_audit.py <out json>"""
import json, sys
import numpy as np, pandas as pd
import features as F, run as RN
df = RN.load_llm(F.build(include_today=False)); df["id"] = df.id.astype(str); df["rk"] = pd.to_numeric(df.dailyRank, errors="coerce")
df = df[df.day >= "2026-01-01"]
K = df[df.known]; out = {"labelled_days_2026": int(df.day.nunique()), "launches": int(len(df)), "known": int(len(K)),
       "days_with_known": int(K.day.nunique()), "known_ranked": int(K.rk.notna().sum()),
       "known_top1": int((K.rk == 1).sum()), "known_top3": int((K.rk <= 3).sum()), "known_top10": int((K.rk <= 10).sum())}
for lo, hi, nm in (("2026-04-01", "2026-10-31", "backtest Apr-Oct"), ("2026-10-25", "2026-11-13", "live Oct 25-Nov 13")):
    k = K[(K.day >= lo) & (K.day <= hi)]
    out[nm] = {"days": int(df[(df.day >= lo) & (df.day <= hi)].day.nunique()), "known": int(len(k)), "days_with_known": int(k.day.nunique()),
               "top1": int((k.rk == 1).sum()), "top3": int((k.rk <= 3).sum()), "top10": int((k.rk <= 10).sum()),
               "known_top3_days": sorted(k[k.rk <= 3].day.unique().tolist())}
A = pd.read_parquet("results/history_retrain_decomp_preds_arm2.parquet"); A["id"] = A.id.astype(str)
full = {d: g.dropna(subset=["rk"]).sort_values("rk").id.tolist() for d, g in df.groupby("day")}
def hits(o, t): return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
res = {}
for col in ("both", "pure"):
    if col not in A: continue
    Aa = A.dropna(subset=["dailyRank", col]); nr = Aa.groupby("day").size(); D10 = sorted(nr[nr >= 10].index)
    a, b = [], []
    for d in D10:
        g = Aa[Aa.day == d]; o = g.sort_values([col, "id"], ascending=[False, True]).id.tolist()
        a.append(hits(o, g.sort_values("dailyRank").id.tolist())); b.append(hits(o, full.get(d, [])))
    a, b = np.array(a), np.array(b)
    res[col] = {"days": len(D10), "a_excluded": a.mean(0).round(1).tolist(), "b_kept_as_misses": b.mean(0).round(1).tolist(),
                "days_where_b_lower_top3": int((b[:, 0] < a[:, 0]).sum())}
out["backtest_183_rule"] = res
json.dump(out, open(sys.argv[1], "w"), indent=1); print(json.dumps(out))
