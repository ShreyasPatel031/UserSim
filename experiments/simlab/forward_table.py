"""Running forward table for the /try simulator (orchestrator 23:15Z Nov 13). Pools every judged day's per-launch rows from
<dir>/forward_sim_<day>_rows.jsonl into <dir>/forward_table.jsonl (one row per launch, day added) and <dir>/forward_summary.json:
p@3 / top-1 per arm (pasted ph|dep, ph|b20, page|dep, page|b20, const) for concerns and questions, paired arm - const, page - pasted,
launch-bootstrap 95% intervals; band coverage and within-day Spearman per day plus the day-mean; n to date. Counts only.
    python forward_table.py <dir>
"""
import glob, json, os, sys
import numpy as np
from scipy.stats import spearmanr
D = sys.argv[1]; rng = np.random.default_rng(0); R = []
for f in sorted(glob.glob(os.path.join(D, "forward_sim_*_rows.jsonl"))):
    day = os.path.basename(f)[12:22]; R += [{**json.loads(l), "day": day} for l in open(f)]
with open(os.path.join(D, "forward_table.jsonl"), "w") as f:
    for r in R: f.write(json.dumps(r) + "\n")
J = [r for r in R if r["judged"]]; L = lambda r, k, a: ((r["labels"].get(k) or {}).get(a) or {}).get("lab") or None
def ci(v):
    v = np.array(v, float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]; return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
out = {"days": sorted({r["day"] for r in R}), "launches": len(R), "judged (>= 5 non-team comments)": len(J)}
for k, nm in (("RC", "concerns"), ("RQ", "questions")):
    o = {}
    for a in ("ph|dep", "ph|b20", "page|dep", "page|b20", "const"):
        P = [np.mean(L(r, k, a)[:3]) for r in J if L(r, k, a)]
        if P: o[a] = {"p@3": ci(P), "top1": ci([float(L(r, k, a)[0]) for r in J if L(r, k, a)])}
        if a != "const": o[f"{a} - const p@3"] = ci([np.mean(L(r, k, a)[:3]) - np.mean(L(r, k, "const")[:3]) for r in J if L(r, k, a) and L(r, k, "const")])
    for a, b in (("page|b20", "ph|b20"), ("page|dep", "ph|dep")):
        o[f"{a} - {b} p@3 (paired)"] = ci([np.mean(L(r, k, a)[:3]) - np.mean(L(r, k, b)[:3]) for r in J if L(r, k, a) and L(r, k, b)])
    out[nm] = o
band = {}
for p in ("ph", "page"):
    per = {}
    for d in out["days"]:
        g = [r for r in R if r["day"] == d and r["band"].get(p) is not None and r.get("final_rank")]
        if len(g) >= 5: per[d] = {"n": len(g), "spearman": round(float(spearmanr([r["band"][p] for r in g], [-r["final_rank"] for r in g]).correlation), 3)}
    band[p] = {"per day": per, "day-mean Spearman": round(float(np.mean([v["spearman"] for v in per.values()])), 3) if per else None, "n": sum(v["n"] for v in per.values())}
out["band (percentile vs final rank)"] = band
json.dump(out, open(os.path.join(D, "forward_summary.json"), "w"), indent=1); print(json.dumps(out)[:2500])
