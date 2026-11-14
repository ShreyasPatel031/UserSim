"""Choose ONE hunter-form variant on 2025 only (orchestrator 15:21Z Nov 14: selection on 2025 month-forward, the 2026 test days untouched).
Month-forward over 2025 (train on 2025 months < m, test month m, Mar-Dec), arm-2 input set (TW.prep, as history_retrain 'both') plus a
candidate group; 5 seeds averaged; top 3 on days with >= 10 ranked launches (secondary top 10). Prints each group and the chosen one.
usage (VM, cwd ~/w/experiments/ph_predict): PYTHONPATH=<dir>:~/w/mk:.:~/w/h25 H25_SRC=~/w/ph_history/2025 ARM=2
  python3 hunter_select.py <hunter_form.parquet>"""
import json, os, sys
import numpy as np, pandas as pd
import lightgbm as lgb
import history_retrain as HR, training_window as TW

HF = pd.read_parquet(sys.argv[1]); HF["id"] = HF.id.astype(str); HF = HF.drop_duplicates("id", keep="last")
df, _ = HR.build(os.path.expanduser(os.environ.get("H25_SRC", "~/w/ph_history/2025")))
df["id"] = df.id.astype(str); df = df.drop_duplicates("id", keep="last").reset_index(drop=True); n = len(df)
df = df.merge(HF.drop(columns=["day"]), on="id", how="left"); assert len(df) == n
G = {"base": [], "all": [c for c in HF.columns if c.startswith("hf_")], "eb": ["hf_eb"],
     "last_trend": ["hf_last_days", "hf_last_rank", "hf_last_logv", "hf_last_rel", "hf_trend3"], "record": ["hf_best_rank", "hf_n_top3", "hf_n_top10"],
     "context": ["hf_topic_rel", "hf_topic_n", "hf_wd_rel", "hf_wd_n", "hf_short_share"]}
d25 = df[df.day < "2026-01-01"].copy(); P = []
for m in [f"2025-{k:02d}" for k in range(3, 13)]:
    tr0, te0 = d25[d25.mon < m], d25[d25.mon == m]
    if te0.empty: continue
    tr, te, cols = TW.prep(tr0, te0)
    cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month") and not c.startswith("hf_")]
    for g, extra in G.items():
        p = np.mean([lgb.LGBMRegressor(random_state=s, **{**TW.P0, "n_jobs": 3}).fit(tr[cols + extra], tr.logv).predict(te[cols + extra]) for s in range(5)], 0)
        P.append(pd.DataFrame({"id": te.id.values, "day": te.day.values, "dailyRank": te.dailyRank.values, "g": g, "pred": p}))
R = pd.concat(P); R["dailyRank"] = pd.to_numeric(R.dailyRank, errors="coerce")
ok = R[R.g == "base"].groupby("day").dailyRank.apply(lambda s: s.notna().sum()); D = set(ok[ok >= 10].index)
res = {}
for g, x in R[R.day.isin(D)].groupby("g"):
    h = []
    for d, gg in x.groupby("day"):
        o = gg.sort_values(["pred", "id"], ascending=[False, True]).id.tolist(); t = gg.dropna(subset=["dailyRank"]).sort_values("dailyRank").id.tolist()
        h.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
    res[g] = np.mean(h, 0).round(2).tolist()
best = max([g for g in res if g != "base"], key=lambda g: (res[g][0], res[g][2]))
print(json.dumps({"days_2025_ge10": len(D), "top3_5_10": res, "chosen": best, "chosen_cols": G[best]}))
