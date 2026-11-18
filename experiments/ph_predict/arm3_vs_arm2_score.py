"""Score arm3_vs_arm2_preds.parquet (pre-registered: primary top 5, secondary top 10, tertiary top 3). Truth rule: final daily rank <= k on days
with >= 10 ranked launches. 2026 truth = warehouse launches.daily_rank (also reported: the frame's dailyRank); 2025 truth = the 2025 lists'
dailyRank (in the parquet). Paired day bootstrap 10,000. usage: python3 arm3_vs_arm2_score.py <preds parquet>"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.abspath(".."))
from pipeline import warehouse as W
P = pd.read_parquet(sys.argv[1]); P["id"] = P.id.astype(str)
Rk = W.query("SELECT CAST(id AS VARCHAR) id, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
P = P.merge(Rk.rename(columns={"daily_rank": "wh_rank"}), on="id", how="left")
rng = np.random.default_rng(0)
def score(X, rk):
    out = []
    for d, g in X.groupby("day"):
        r = pd.to_numeric(g[rk], errors="coerce")
        if r.notna().sum() < 10: continue
        row = []
        for col in ("arm2", "arm3"):
            o = g.assign(s=g[col]).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            row.append([len(set(o[:k]) & set(g.id[r <= k])) / k * 100 for k in (3, 5, 10)])
        out.append(row)
    A = np.array(out); x = A[:, 1] - A[:, 0]; b = np.array([x[rng.integers(0, len(x), len(x))].mean(0) for _ in range(10000)])
    ci = [f"{x[:, k].mean():+.1f} [{np.percentile(b[:, k], 2.5):+.1f}, {np.percentile(b[:, k], 97.5):+.1f}]" for k in range(3)]
    clear = [bool(np.percentile(b[:, k], 2.5) > 0) for k in range(3)]
    return len(A), A[:, 0].mean(0).round(1).tolist(), A[:, 1].mean(0).round(1).tolist(), ci, clear
for yr, rk in (("2026", "wh_rank"), ("2026", "dailyRank"), ("2025", "dailyRank")):
    n, a2, a3, ci, clear = score(P[P.year == yr], rk)
    print(f"{yr} truth={rk} days={n} arm2 {a2} arm3 {a3} | arm3-arm2 top3 {ci[0]} | top5 (PRIMARY) {ci[1]} | top10 {ci[2]} | clear of 0 (3/5/10): {clear}")
