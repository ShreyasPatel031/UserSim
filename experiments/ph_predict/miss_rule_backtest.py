"""Backtest of the one rule chosen by miss_anatomy_arm3 (pre-registered: results/arm3_miss_anatomy_prereg.md).
Re-ranker z(arm3) + w * z(feature) within day; w from {0, 0.1, 0.2, 0.3, 0.5, 1.0} chosen leave-one-month-out by top 5 + top 3 hits
(ties -> smaller w); paired vs arm 3 alone, day bootstrap 95% (10,000). Rows: results/arm3_vs_arm2_preds.parquet (leak-free month-forward
arm-3 predictions); features: tmp/ph_ops/bt_feats.parquet (history_retrain build, 2025 old-row NaN rules). Missing feature -> day median.
usage: python miss_rule_backtest.py <feature> -> results/miss_rule_backtest_<feature>.json"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); R = lambda p: os.path.join(HERE, "results", p)
WS = [0, 0.1, 0.2, 0.3, 0.5, 1.0]
z = lambda s: (s - s.mean()) / (s.std(ddof=0) or 1.0)


def hits(g, col):
    o = g.sort_values([col, "id"], ascending=[False, True]).id.tolist(); t = g[g.dailyRank.notna()]
    return [len(set(o[:k]) & set(t[t.dailyRank <= k].id)) / k for k in (3, 5, 10)]


def boot(x, n=10000):
    x = np.asarray(x); rng = np.random.default_rng(0); bs = np.array([x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)])
    return [round(100 * x.mean(), 1), round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1)]


def run(P, feat, year):
    P = P[P.year == year].copy(); P["mon"] = P.day.str[:7]
    days = [d for d, g in P.groupby("day") if g.dailyRank.notna().sum() >= 10]   # restated rule: >= 10 ranked launches (183 / 204 days)
    P = P[P.day.isin(days)]
    if P[feat].isna().all(): return {"n_days": len(days), "note": f"{feat} is all-null in {year}"}
    P["f"] = P.groupby("day")[feat].transform(lambda s: s.fillna(s.median() if s.notna().any() else 0.0))
    P["za"] = P.groupby("day").arm3.transform(z); P["zf"] = P.groupby("day").f.transform(z)
    H = {}
    for w in WS:
        P["s"] = P.za + w * P.zf; H[w] = {d: hits(g, "s") for d, g in P.groupby("day")}
    mon = P.groupby("day").mon.first().to_dict(); res, ch = {}, {}
    for m in sorted(set(mon.values())):
        oth = [d for d in days if mon[d] != m]
        w = max(WS, key=lambda w: (sum(H[w][d][1] + H[w][d][0] for d in oth), -w)); ch[m] = w
        for d in days:
            if mon[d] == m: res[d] = (H[0][d], H[w][d])
    base = np.array([res[d][0] for d in days]); rr = np.array([res[d][1] for d in days]); D = rr - base
    return {"n_days": len(days), "arm3_3_5_10": [round(100 * v, 1) for v in base.mean(0)], "rule_3_5_10": [round(100 * v, 1) for v in rr.mean(0)],
            "diff_top3": boot(D[:, 0]), "diff_top5": boot(D[:, 1]), "diff_top10": boot(D[:, 2]), "w_by_held_out_month": ch,
            "feature_null_rate": round(float(P[feat].isna().mean()), 3)}


def main(feat):
    P = pd.read_parquet(R("arm3_vs_arm2_preds.parquet")); P["id"] = P.id.astype(str); P["day"] = P.day.astype(str).str[:10]
    t = tempfile.mkdtemp() + "/f.parquet"
    subprocess.run(["gsutil", "-q", "cp", "gs://usersim-bakeoff-347838016394/usersim_sim/tmp/ph_ops/bt_feats.parquet", t], check=True)
    Fb = pd.read_parquet(t); Fb["id"] = Fb.id.astype(str); P = P.merge(Fb[["id", feat]], on="id", how="left")
    res = {"feature": feat, "rule": "z(arm3) + w z(feature) within day, w leave-one-month-out", "2026": run(P, feat, "2026"), "2025": run(P, feat, "2025")}
    a = res["2026"]; ok = "diff_top3" in a and (a["diff_top3"][1] > 0 or a["diff_top5"][1] > 0)
    res["decision"] = "DEPLOY CANDIDATE (2026 top-3 or top-5 interval clear of 0)" if ok else "NOT CLEAR: scored shadow line"
    json.dump(res, open(R(f"miss_rule_backtest_{feat}.json"), "w"), indent=1); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
