"""Leak check of the honest backtest (orchestrator 05:20Z Nov 12): per variant (training_window.py leave-outs of the llm /
promo sources), top 3/5/10, our #1/#2/#3 pick in the final top 3, exact winner at #1, and the #1-#2 margin (prediction
gap in log votes, and as a within-day z), over all scored days and Sep - Oct; paired day-bootstrap CIs vs ref.
usage: python score_leak.py <preds.parquet> -> results/leak_check.json + .md"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))


def day_stats(A, col):
    out = {}
    for d, g in A.groupby("day"):
        if (g.dailyRank <= 10).sum() < 10:
            continue
        o = g.sort_values(col, ascending=False); ids = o.id.tolist(); rk = dict(zip(g.id, g.dailyRank))
        t = {k: set(g[g.dailyRank <= k].id) for k in (3, 5, 10)}
        p = o[col].values; sd = g[col].std() or 1.0
        out[d] = {"top3": len(set(ids[:3]) & t[3]) / 3, "top5": len(set(ids[:5]) & t[5]) / 5, "top10": len(set(ids[:10]) & t[10]) / 10,
                  "p1_top3": float(ids[0] in t[3]), "p2_top3": float(ids[1] in t[3]), "p3_top3": float(ids[2] in t[3]),
                  "exact1": float(rk.get(ids[0]) == 1), "margin": float(p[0] - p[1]), "margin_z": float((p[0] - p[1]) / sd)}
    return pd.DataFrame(out).T


def boot(x, rng):
    x = np.asarray(x, float); b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(4000)]
    return [round(float(np.percentile(b, 2.5)), 3), round(float(np.percentile(b, 97.5)), 3)]


def main(p):
    rng = np.random.default_rng(0); A = pd.read_parquet(p); A = A[A.dailyRank.notna()]
    V = [c for c in ("ref", "no_llm", "no_llm_site", "no_llm_pitch", "no_llm_brand", "no_promo", "no_llm_promo", "no_maker_age", "no_maker_prof") if c in A]
    res, md = {}, ["# Leak check: honest month-forward backtest without the llm / promo sources (5 seeds)", ""]
    M = ["top3", "top5", "top10", "p1_top3", "p2_top3", "p3_top3", "exact1"]
    for nm, U in (("all scored days (Mar - Nov 10)", A), ("Sep - Oct", A[A.mon.isin(["2026-09", "2026-10"])])):
        S = {v: day_stats(U, v) for v in V}; base = S["ref"]; res[nm] = {}
        md += [f"## {nm}: {len(base)} days (days with all of the final top 10 ranked)", "",
               "| variant | top 3 | top 5 | top 10 | #1 in top 3 | #2 in top 3 | #3 in top 3 | exact winner | #1-#2 margin (median, z) | minus ref top 3 [95% CI] | minus ref #1 in top 3 |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        for v in V:
            s = S[v]; r = {m: round(100 * float(s[m].mean()), 1) for m in M}
            r["margin_med"] = round(float(s.margin.median()), 3); r["margin_z_med"] = round(float(s.margin_z.median()), 2)
            if v != "ref":
                d3 = (s.top3 - base.top3).values; d1 = (s.p1_top3 - base.p1_top3).values
                r["d_top3"] = [round(100 * float(d3.mean()), 1)] + [round(100 * x, 1) for x in boot(d3, rng)]
                r["d_p1"] = [round(100 * float(d1.mean()), 1)] + [round(100 * x, 1) for x in boot(d1, rng)]
            res[nm][v] = r
            f = lambda x: f"{x[0]:+.1f} [{x[1]:+.1f}, {x[2]:+.1f}]" if x else "-"
            md.append(f"| {v} | {r['top3']} | {r['top5']} | {r['top10']} | {r['p1_top3']} | {r['p2_top3']} | {r['p3_top3']} | {r['exact1']} | "
                      f"{r['margin_med']} ({r['margin_z_med']}) | {f(r.get('d_top3'))} | {f(r.get('d_p1'))} |")
        md.append("")
    json.dump(res, open(os.path.join(HERE, "results", "leak_check.json"), "w"), indent=1)
    open(os.path.join(HERE, "results", "leak_check.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main(sys.argv[1])
