"""Score config_parity.py on the live days: daily top 3/5/10 per config (00:05 rows vs final daily ranks of the final line-up,
as parity_live), paired day-bootstrap differences vs the deployed config (live_daily).
usage: python score_config_parity.py <config_parity_rows.parquet> -> results/config_parity.json + .md"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
C = ["live_daily", "honest_daily", "honest_month", "live_month", "honest_nopage_daily"]


def per_day(R, col, k):
    out = {}
    for d, g in R.groupby("day"):
        truth = set(g[g["rank"] <= k].id)
        if len(truth) < k:
            continue
        out[d] = len(set(g.nlargest(k, col).id) & truth) / k
    return pd.Series(out)


def boot(x, rng):
    x = x.dropna().values; b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(4000)]
    return [round(100 * float(x.mean()), 1), round(100 * float(np.percentile(b, 2.5)), 1), round(100 * float(np.percentile(b, 97.5)), 1)]


def main(p):
    rng = np.random.default_rng(0); R = pd.read_parquet(p)
    base = {k: per_day(R, "live_daily", k) for k in (3, 5, 10)}
    res = {"days": sorted(R.day.unique()), "table": {}}
    md = [f"# Deployed vs honest 00:05 configuration on the live days ({R.day.nunique()} days, 00:05 rows, 5 seeds)", "",
          "Params identical in all configs (LIVE_PARAMS = ctrl.fit settings); configs differ in feature set and refit cadence.", "",
          "| config | top 3 | top 5 | top 10 | minus live_daily: top 3 | top 5 | top 10 |", "|---|---|---|---|---|---|---|"]
    for c in C:
        cur = {k: per_day(R, c, k) for k in (3, 5, 10)}
        r = {f"top{k}": round(100 * float(cur[k].mean()), 1) for k in (3, 5, 10)}
        if c != "live_daily":
            r.update({f"d{k}": boot(cur[k] - base[k], rng) for k in (3, 5, 10)})
        res["table"][c] = r
        md.append(f"| {c} | {r['top3']} | {r['top5']} | {r['top10']} | " + (" | ".join(f"{r[f'd{k}'][0]:+.1f} [{r[f'd{k}'][1]:+.1f}, {r[f'd{k}'][2]:+.1f}]" for k in (3, 5, 10)) if c != "live_daily" else "- | - | -") + " |")
    json.dump(res, open(os.path.join(HERE, "results", "config_parity.json"), "w"), indent=1)
    open(os.path.join(HERE, "results", "config_parity.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main(sys.argv[1])
