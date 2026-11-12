"""Score training_window.py's out-of-fold predictions: daily top 3/5/10 per variant vs ref (month-forward expanding),
paired day bootstrap 95% CIs, over all test days and over the recent months (Sep - Nov). Days with all top-k ranked.
usage: python score_training_window.py <month.parquet> [<daily.parquet>] -> results/training_window.json + .md"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))


def per_day(A, col, k):
    return pd.Series({d: len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k for d, g in A.groupby("day") if (g.dailyRank <= k).sum() == k})


def boot(d, rng):
    d = d.dropna().values; b = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(4000)]
    return [round(100 * float(d.mean()), 1), round(100 * float(np.percentile(b, 2.5)), 1), round(100 * float(np.percentile(b, 97.5)), 1)]


def table(A, V, rng):
    out = {}
    base = {k: per_day(A, "ref", k) for k in (3, 5, 10)}
    for v in V:
        cur = {k: per_day(A, v, k) for k in (3, 5, 10)}
        r = {f"top{k}": round(100 * float(cur[k].mean()), 1) for k in (3, 5, 10)}
        if v != "ref":
            r.update({f"d{k}": boot(cur[k] - base[k], rng) for k in (3, 5, 10)})
        out[v] = r
    return out, len(base[3])


def main(paths):
    rng = np.random.default_rng(0)
    A = pd.read_parquet(paths[0])
    for q in paths[1:]:
        D = pd.read_parquet(q); D = D[["id"] + [c for c in D.columns if c not in A.columns]]; A = A.merge(D, on="id", how="inner")
    A = A[A.dailyRank.notna()]
    V = [c for c in ("ref", "daily", "live_daily", "live_month", "honest_nopage_month", "roll60", "roll90", "roll120", "hl30", "hl60", "hl90", "dow", "split") if c in A]
    res = {}
    md = ["# 00:05 launch model: training window (honest setup, 5 seeds)", ""]
    for nm, U in (("all test days (Mar - Nov 10)", A), ("Sep - Nov 10", A[A.mon >= "2026-09"]), ("Nov 1 - 10", A[A.mon == "2026-11"])):
        t, n = table(U, V, rng); res[nm] = {"days": n, "table": t}
        md += [f"## {nm}: {n} days", "", "| variant | top 3 | top 5 | top 10 | minus ref: top 3 | top 5 | top 10 |", "|---|---|---|---|---|---|---|"]
        for v, r in t.items():
            md.append(f"| {v} | {r['top3']} | {r['top5']} | {r['top10']} | " + (" | ".join(f"{r[f'd{k}'][0]:+.1f} [{r[f'd{k}'][1]:+.1f}, {r[f'd{k}'][2]:+.1f}]" for k in (3, 5, 10)) if v != "ref" else "- | - | -") + " |")
        md.append("")
    json.dump(res, open(os.path.join(HERE, "results", "training_window.json"), "w"), indent=1)
    open(os.path.join(HERE, "results", "training_window.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main(sys.argv[1:])
