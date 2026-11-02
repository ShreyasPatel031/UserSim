"""Top 3 / 5 / 10 on Product Hunt's daily, weekly and monthly leaderboards, for any prediction columns in newsim_eval
SAVE=1 parquets (scores are log-vote predictions, comparable across the days of a month). Real ranks come from the
store (out_dailyRank / out_weeklyRank / out_monthlyRank). A list counts when its real top k is complete among the
scored launches. Weeks are Product Hunt's (Monday-Sunday). Intervals: bootstrap over lists (days, weeks or months),
paired against the first column. With 4 test months the monthly interval is wide; it is reported as is.
usage: SIMLAB_DATA=data_v2 python lists_score.py A.parquet:col [B.parquet:col ...] -> prints, and results/lists_score.json"""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store

RANK = {"daily": "out_dailyRank", "weekly": "out_weeklyRank", "monthly": "out_monthlyRank"}


def per_list(T, col, board, k):
    g_key = {"daily": "day", "weekly": "week", "monthly": "mon"}[board]
    out = {}
    for key, g in T.groupby(g_key):
        real = g[g[RANK[board]] <= k]
        if len(real) == k:
            out[key] = len(set(g.nlargest(k, col).id) & set(real.id)) / k
    return out


def main(specs):
    P, I, E = store.load()
    I = I.assign(id=I.id.astype(str))[["id"] + list(RANK.values())]
    T, cols = None, []
    for k, s in enumerate(specs):
        f, c = s.rsplit(":", 1); X = pd.read_parquet(f); X["id"] = X.id.astype(str); n = f"m{k}"
        X = X[["id", "day", c]].rename(columns={c: n})
        T = X if T is None else T.merge(X[["id", n]], on="id")
        cols.append(n)
    T = T.merge(I, on="id")
    T["week"] = pd.to_datetime(T.day).dt.strftime("%G-W%V"); T["mon"] = T.day.str[:7]
    rng = np.random.default_rng(0); res = {"launches": len(T), "from": T.day.min(), "to": T.day.max(), "boards": {}}
    for board in ("daily", "weekly", "monthly"):
        res["boards"][board] = {}
        for k in (3, 5, 10):
            ref = per_list(T, cols[0], board, k); line = {}
            for s, c in zip(specs, cols):
                cur = per_list(T, c, board, k); keys = sorted(set(ref) & set(cur))
                d = np.array([cur[x] - ref[x] for x in keys])
                bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(5000)] if len(d) else [0]
                line[s] = {"value": round(100 * float(np.mean([cur[x] for x in keys])), 1) if keys else None, "lists": len(keys),
                           "vs_first": round(100 * float(d.mean()), 1) if len(d) else None,
                           "ci": [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])]}
            res["boards"][board][f"top {k}"] = line
    for board, b in res["boards"].items():
        print(board)
        for kk, line in b.items():
            print("  ", kk, " | ".join(f"{s.split(':')[-1]} {v['value']} ({v['vs_first']:+.1f}, {v['ci'][0]:+.1f} to {v['ci'][1]:+.1f}; n={v['lists']})" for s, v in line.items()))
    json.dump(res, open("results/lists_score.json", "w"), indent=1)
    return res


if __name__ == "__main__":
    main(sys.argv[1:])
