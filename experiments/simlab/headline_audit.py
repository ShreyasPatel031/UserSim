"""Audit of the arm-2 / clean headline (orchestrator 23:30Z Nov 13). Read-only. Counts only.
PH ops' scoring (history_retrain.py on claude/ph-ops-agent): field = launches of the day with features, MINUS launches any LLM pass
flagged 'known' (run.load_llm: the model says it remembers the launch; union over pitch/site/brand/full, Gemini and Claude); true top k
= the k smallest dailyRank WITHIN that field; model order = score desc, ties by id; overlap/k; Apr 1 - Oct 31, every day in the file.
Full field here = the warehouse launches table (official daily_rank). (a) PH ops' rule on its own file. (b) plain: true top k = official
daily_rank 1..k among all featured launches; launches missing from the arm-2 file are ranked last by the model (cannot be picked) -
lower bound - and alternatively placed at their day's median score. Same for clean_v3 (honest_preds_v2), and arm 2 - clean.
    python headline_audit.py <scratchpad> <arm2 parquet> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
SP, A2P, OUT = sys.argv[1:4]; rng = np.random.default_rng(0)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
A = pd.read_parquet(A2P); A["id"] = A.id.astype(str); days = sorted(A.day.unique())
W = L[L.day.isin(days) & L.daily_rank.notna()][["id", "day", "daily_rank"]].copy(); W["daily_rank"] = W.daily_rank.astype(float)
H = pd.read_parquet(f"{SP}/honest_preds_v2.parquet")[["id", "honest"]]; H["id"] = H.id.astype(str)
def score(G, col, rk):
    out = []
    for d, g in G.groupby("day"):
        t = g.sort_values(rk).id.tolist(); o = g.sort_values([col, "id"], ascending=[False, True]).id.tolist(); out.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
    return np.array(out)
def ci(v):
    bs = np.array([v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(4000)])
    return [[round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
res = {"design": __doc__.split("\n    python")[0], "days": len(days)}
F = W.merge(A[["id", "both"]], on="id", how="left").merge(H, on="id", how="left")
miss = F[F.both.isna()]; res["field"] = {"warehouse launches (full field)": len(F), "arm2 file launches": len(A), "full-field launches missing from arm2 file": len(miss),
    "days affected": int(miss.day.nunique()), "missing launches with official rank <= 3 / <= 10": [int((miss.daily_rank <= 3).sum()), int((miss.daily_rank <= 10).sum())],
    "arm2 ids not in warehouse": int((~A.id.isin(W.id)).sum()), "missing honest (clean) score in full field": int(F.honest.isna().sum()),
    "days whose ranks are not 1..n contiguous in warehouse": int(sum(1 for _, g in W.groupby("day") if sorted(g.daily_rank) != list(range(1, len(g) + 1)))),
    "rank disagreements arm2 dailyRank vs warehouse daily_rank": int((A.merge(W, on="id").pipe(lambda m: (m.dailyRank.astype(float) != m.daily_rank)).sum()))}
# (a) PH ops rule on its own file (field = arm2 file, true = smallest dailyRank in file)
Aa = A.merge(H, on="id", how="left"); both_a = score(Aa, "both", "dailyRank"); Ha = Aa.dropna(subset=["honest"]); 
res["(a) PH ops rule, arm2 file"] = {"arm2": ci(both_a), "n days": len(both_a)}
# clean on the same field (days/launches where honest exists)
common = Aa.dropna(subset=["honest"]); ok = common.groupby("day").id.transform("count") == Aa.groupby("day").id.transform("count").reindex(common.index)
ca, cb = score(common, "both", "dailyRank"), score(common, "honest", "dailyRank")
res["(a) on launches with both scores"] = {"days": len(ca), "arm2": ci(ca), "clean_v3": ci(cb), "arm2 - clean": ci(ca - cb)}
# (b) plain: official ranks 1..k over full field
for nm, fill in (("unscored ranked last", "last"), ("unscored at day median", "median")):
    G = F.copy()
    for c in ("both", "honest"):
        G[c] = G[c].fillna(G.groupby("day")[c].transform("min") - 1e6) if fill == "last" else G[c].fillna(G.groupby("day")[c].transform("median"))
    G = G.dropna(subset=["both", "honest"]); x, y = score(G, "both", "daily_rank"), score(G, "honest", "daily_rank")
    res[f"(b) plain official top k, full field, {nm}"] = {"days": len(x), "arm2": ci(x), "clean_v3": ci(y), "arm2 - clean": ci(x - y)}
os.makedirs(OUT, exist_ok=True); json.dump(res, open(os.path.join(OUT, "headline_audit.json"), "w"), indent=1); print(json.dumps({k: v for k, v in res.items() if k != "design"}))
