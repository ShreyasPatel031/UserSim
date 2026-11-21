"""WHO backtest on the orchestrator's backtest_v1 set (Oct 22 - Nov 20, Nov 20 segment cut): can an as-of predictor beat the base mix?
P3 = backer group mix of earlier launches (previous 30 days, strictly before D) that share the launch's topics (weighted by topic overlap);
BASE = pooled backer group mix of all launches in the previous 30 days. Both use only cohorts of days < D. Group labels are the Nov 20 cut
(fit after most of these days): a labelling caveat, the predictions themselves use only earlier days' cohorts.
    python cohort_topic_backtest.py <backtest_v1 dir> <out json>"""
import json, sys
import numpy as np, pandas as pd
D_, OUT = sys.argv[1:3]; rng = np.random.default_rng(0)
C = [json.loads(l) for l in open(f"{D_}/cohort.jsonl")]; L = {r["launch_id"]: r for r in map(json.loads, open(f"{D_}/launches.jsonl"))}
def norm(d):
    d = {k: v for k, v in (d or {}).items() if k != "other"}; s = sum(d.values()); return {k: v / s for k, v in d.items()} if s else {}
def jsd(p, q):
    ks = sorted(set(p) | set(q)); a = np.array([p.get(k, 0) for k in ks], float); b = np.array([q.get(k, 0) for k in ks], float); a, b = a / a.sum(), b / b.sum(); m = (a + b) / 2
    kl = lambda x, y: np.sum(np.where(x > 0, x * np.log2(np.where(x > 0, x, 1) / np.where(y > 0, y, 1)), 0)); return float(np.sqrt(max(0.5 * kl(a, m) + 0.5 * kl(b, m), 0)))
for r in C: r["mix"] = norm(r.get("backers_by_group")); r["n"] = sum(v for k, v in (r.get("backers_by_group") or {}).items() if k != "other"); r["topics"] = set(L.get(r["launch_id"], {}).get("topics") or [])
days = sorted({r["day"] for r in C}); rows = []
for D in days:
    lo = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); past = [r for r in C if lo <= r["day"] < D and r["n"] >= 5]
    if len(past) < 30: continue
    pool = {}; [pool.__setitem__(k, pool.get(k, 0) + v) for r in past for k, v in (r.get("backers_by_group") or {}).items() if k != "other"]; base = norm(pool)
    for r in [x for x in C if x["day"] == D and x["n"] >= 20]:
        acc, wsum = {}, 0.0
        for p in past:
            w = len(r["topics"] & p["topics"])
            if w:
                wsum += w
                for k, v in p["mix"].items(): acc[k] = acc.get(k, 0) + w * v
        p3 = {k: v / wsum for k, v in acc.items()} if wsum else base
        lt = L.get(r["launch_id"], {})
        rows.append({"day": D, "launch_id": r["launch_id"], "n_backers": r["n"], "coverage": r.get("coverage"), "rank": r.get("final_daily_rank"), "votes": r.get("votes"),
                     "jsd_base": jsd(base, r["mix"]), "jsd_p3": jsd(p3, r["mix"]), "top_share": max(r["mix"].values()), "topic": (sorted(r["topics"]) or ["none"])[0],
                     "web_testable": lt.get("web_testable")})
R = pd.DataFrame(rows); R["d"] = R.jsd_p3 - R.jsd_base
def boot(col, df=R):
    d = sorted(df.day.unique()); bs = [pd.concat([df[df.day == x] for x in rng.choice(d, len(d))])[col].mean() for _ in range(2000)]
    return [round(float(df[col].mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(df)), len(d)]
out = {"set": "results/calibration/backtest_v1 (Nov 20 cut)", "launches_scored (>= 20 held backers)": int(len(R)), "days": int(R.day.nunique()),
       "coverage_median": float(R.coverage.median()), "JSD base": boot("jsd_base"), "JSD P3 topic-neighbour": boot("jsd_p3"), "P3 minus base (paired)": boot("d"),
       "note": "[mean, day-bootstrap 2.5%, 97.5%, launches, days]",
       "per_day": R.groupby("day").agg(launches=("launch_id", "size"), jsd_base=("jsd_base", "mean"), jsd_p3=("jsd_p3", "mean"), coverage=("coverage", "median")).round(3).reset_index().to_dict("records")}
x = R.copy(); x["rank_band"] = pd.cut(x["rank"], [0, 5, 10, 1e9], labels=["1-5", "6-10", "11+"]); x["vote_band"] = pd.cut(x.votes, [0, 100, 250, 1e9], labels=["<100", "100-250", ">250"])
for c in ("rank_band", "vote_band", "topic"):
    g = x.groupby(c, observed=True).agg(n=("d", "size"), jsd_p3=("jsd_p3", "mean"), jsd_base=("jsd_base", "mean"), p3_minus_base=("d", "mean")).round(3)
    out[f"by_{c}"] = {str(k): v for k, v in g[g.n >= (15 if c == "topic" else 1)].to_dict("index").items()}
json.dump(out, open(OUT, "w"), indent=1, default=str); R.to_parquet(OUT.replace(".json", "_rows.parquet"))
print(json.dumps({k: v for k, v in out.items() if k not in ("per_day",)}, indent=1, default=str))
