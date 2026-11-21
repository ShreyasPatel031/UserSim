"""PREREG addendum 2: P6 = w*P3 + (1-w)*BASE, w by expected-rank band (00:05 forecast), fit Oct 22-Nov 10, test Nov 11-20.
    python cohort_blend.py <backtest_v1 dir> <out json>"""
import json, sys
import numpy as np, pandas as pd
D_, OUT = sys.argv[1:3]; rng = np.random.default_rng(0)
C = [json.loads(l) for l in open(f"{D_}/cohort.jsonl")]; L = {r["launch_id"]: r for r in map(json.loads, open(f"{D_}/launches.jsonl"))}
PR = {r["launch_id"]: r for r in map(json.loads, open(f"{D_}/predictions.jsonl"))}
def norm(d):
    d = {k: v for k, v in (d or {}).items() if k != "other"}; s = sum(d.values()); return {k: v / s for k, v in d.items()} if s else {}
def jsd(p, q):
    ks = sorted(set(p) | set(q)); a = np.array([p.get(k, 0) for k in ks], float); b = np.array([q.get(k, 0) for k in ks], float); a, b = a / a.sum(), b / b.sum(); m = (a + b) / 2
    kl = lambda x, y: np.sum(np.where(x > 0, x * np.log2(np.where(x > 0, x, 1) / np.where(y > 0, y, 1)), 0)); return float(np.sqrt(max(0.5 * kl(a, m) + 0.5 * kl(b, m), 0)))
for r in C: r["mix"] = norm(r.get("backers_by_group")); r["n"] = sum(v for k, v in (r.get("backers_by_group") or {}).items() if k != "other"); r["topics"] = set(L.get(r["launch_id"], {}).get("topics") or [])
def band(lid):
    f = (PR.get(lid) or {}).get("forecast_0005") or {}; pr = f.get("predicted_rank")
    return "none" if pr is None else ("1-5" if pr <= 5 else "6-10" if pr <= 10 else "11+")
rows = []
for D in sorted({r["day"] for r in C}):
    lo = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); past = [r for r in C if lo <= r["day"] < D and r["n"] >= 5]
    if len(past) < 30: continue
    pool = {}; [pool.__setitem__(k, pool.get(k, 0) + v) for r in past for k, v in (r.get("backers_by_group") or {}).items() if k != "other"]; base = norm(pool)
    for r in [x for x in C if x["day"] == D and x["n"] >= 20]:
        acc, ws = {}, 0.0
        for p in past:
            w = len(r["topics"] & p["topics"])
            if w:
                ws += w
                for k, v in p["mix"].items(): acc[k] = acc.get(k, 0) + w * v
        p3 = {k: v / ws for k, v in acc.items()} if ws else base
        rows.append({"day": D, "lid": r["launch_id"], "eband": band(r["launch_id"]), "rank": r.get("final_daily_rank"), "real": r["mix"], "base": base, "p3": p3})
R = pd.DataFrame(rows)
blend = lambda w, a, b: {k: w * a.get(k, 0) + (1 - w) * b.get(k, 0) for k in set(a) | set(b)}
GRID = np.round(np.arange(0, 1.01, 0.1), 1); TR = R[R.day <= "2026-11-10"]; TE = R[R.day >= "2026-11-11"].copy()
W = {}
for b in ("1-5", "6-10", "11+", "none"):
    x = TR[TR.eband == b]
    if len(x) < 10: W[b] = None; continue
    W[b] = float(GRID[int(np.argmin([np.mean([jsd(blend(w, p, q), t) for p, q, t in zip(x.p3, x.base, x.real)]) for w in GRID]))])
wall = float(GRID[int(np.argmin([np.mean([jsd(blend(w, p, q), t) for p, q, t in zip(TR.p3, TR.base, TR.real)]) for w in GRID]))])
TE["w"] = [W.get(b) if W.get(b) is not None else wall for b in TE.eband]
TE["jsd_base"] = [jsd(q, t) for q, t in zip(TE.base, TE.real)]; TE["jsd_p3"] = [jsd(p, t) for p, t in zip(TE.p3, TE.real)]
TE["jsd_p6"] = [jsd(blend(w, p, q), t) for w, p, q, t in zip(TE.w, TE.p3, TE.base, TE.real)]
TE["jsd_p6_flat"] = [jsd(blend(wall, p, q), t) for p, q, t in zip(TE.p3, TE.base, TE.real)]
TE["d_base"] = TE.jsd_p6 - TE.jsd_base; TE["d_p3"] = TE.jsd_p6 - TE.jsd_p3; TE["d_flat"] = TE.jsd_p6_flat - TE.jsd_base
def boot(col, df=TE):
    d = sorted(df.day.unique()); bs = [pd.concat([df[df.day == x] for x in rng.choice(d, len(d))])[col].mean() for _ in range(2000)]
    return [round(float(df[col].mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4), int(len(df)), len(d)]
TE["rank_band"] = pd.cut(TE["rank"], [0, 5, 10, 1e9], labels=["1-5", "6-10", "11+"]).astype(str)
out = {"prereg": "PREREG.md addendum 2", "train": "2026-10-22..2026-11-10 launches %d" % len(TR), "weights_by_expected_band": W, "flat_weight": wall,
       "train_band_counts": TR.eband.value_counts().to_dict(), "test_band_counts": TE.eband.value_counts().to_dict(),
       "test": {"JSD base": boot("jsd_base"), "JSD P3": boot("jsd_p3"), "JSD P6": boot("jsd_p6"), "JSD P6 flat w": boot("jsd_p6_flat"),
                "P6 minus base": boot("d_base"), "P6 minus P3": boot("d_p3"), "P6flat minus base": boot("d_flat")},
       "by_final_rank_band": {b: {"n": int(len(x)), "base": round(x.jsd_base.mean(), 3), "p3": round(x.jsd_p3.mean(), 3), "p6": round(x.jsd_p6.mean(), 3)} for b, x in TE.groupby("rank_band")},
       "pass": None, "note": "[mean, day-bootstrap 2.5%, 97.5%, launches, days]"}
out["pass"] = bool(out["test"]["P6 minus base"][2] < 0 and out["test"]["P6 minus P3"][2] < 0)
json.dump(out, open(OUT, "w"), indent=1); print(json.dumps(out, indent=1))
