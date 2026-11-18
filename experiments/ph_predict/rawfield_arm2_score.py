"""Score rawfield_arm2.py (usage: python rawfield_arm2_score.py <preds parquet in results/> <tag>): paired (drop - arm 2) top 3/5/10, day bootstrap 95% (4000). 2026: truth_daily.json; 2025: stored dailyRank.
Also checks the re-run arm 2 against the stored published backtest (history_retrain_decomp_preds_arm2.parquet 'both')."""
import json, os, subprocess
import numpy as np, pandas as pd
R = lambda p: os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", p)
P = pd.read_parquet(R("" + __import__("sys").argv[1] + "")); P["id"] = P.id.astype(str)
T = json.loads(subprocess.run(["gsutil", "cat", "gs://usersim-bakeoff-347838016394/usersim_sim/results/web/truth_daily.json"], capture_output=True, text=True, check=True).stdout)["days"]
T26 = {d: {str(i): r for i, r in v["ranks"].items()} for d, v in T.items() if len(v.get("ranks", {})) >= 10}
A = pd.read_parquet(R("history_retrain_decomp_preds_arm2.parquet")); A["id"] = A.id.astype(str)
m = P.merge(A[["id", "both"]], on="id"); out = {"rerun_vs_stored_arm2_max_abs": round(float((m.arm2 - m.both).abs().max()), 6), "rerun_vs_stored_corr": round(float(m[["arm2", "both"]].corr().iloc[0, 1]), 6)}
def hits(o, t): return [len(set(o[:k]) & {i for i, r in t.items() if r <= k}) / k * 100 for k in (3, 5, 10)]
for yr in ("2026", "2025"):
    Q = P[P.year == yr]; H = []
    if Q.empty: continue
    for d, g in Q.groupby("day"):
        t = T26.get(d) if yr == "2026" else {i: r for i, r in zip(g.id, g.dailyRank) if pd.notna(r)}
        if t is None or len(t) < 10: continue
        H.append([hits(g.sort_values([c, "id"], ascending=[False, True]).id.tolist(), t) for c in ("arm2", "plus")])
    H = np.array(H); D = H[:, 1] - H[:, 0]; rng = np.random.default_rng(0); n = len(H)
    bs = np.array([D[rng.integers(0, n, n)].mean(0) for _ in range(4000)])
    out[yr] = {"n_days": n, "arm2": H[:, 0].mean(0).round(1).tolist(), "plus": H[:, 1].mean(0).round(1).tolist(),
               "diff": D.mean(0).round(1).tolist(), "ci_lo": np.percentile(bs, 2.5, 0).round(1).tolist(), "ci_hi": np.percentile(bs, 97.5, 0).round(1).tolist()}
print(json.dumps(out, indent=1)); json.dump(out, open(R("rawfield_arm2_" + __import__("sys").argv[2] + ".json"), "w"), indent=1)
