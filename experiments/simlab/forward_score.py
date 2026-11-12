"""Score the forward page-read band test (forward_band.py) against final daily ranks. Counts only.
Per launch: band v1 (as served: percentile, rank band), frozen d_both B0 (<= Aug 31), v2 run 1 / run 2 (S_PRIMARY), facts-only stack.
Pooled over all scored days: Spearman of each percentile with -rank; paired launch bootstrap of (v2 - v1), (facts - v1);
v1 rank-band coverage (nominal 80%) and percentile-of-day check; also the same within day (mean of per-day Spearman, days with >= 5).
Reactions / concerns / questions are stored for the judge pass (reactions_eval-style) once comment truth is complete (+3 days).
    python forward_score.py <scratchpad> [out json]
"""
import glob, gzip, json, os, subprocess, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
SP = sys.argv[1]; OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SP, "forward/forward_score.json"); BK = "gs://usersim-bakeoff-347838016394/usersim_sim"
rng = np.random.default_rng(0); loc = os.path.join(SP, "forward/pulled"); os.makedirs(loc, exist_ok=True)
subprocess.run(["gsutil", "-q", "-m", "rsync", "-r", "-x", r".*\.pkl$", f"{BK}/tmp/e5/band/forward/", loc])
os.makedirs(os.path.expanduser("~/.usersim_sim/launches"), exist_ok=True)
subprocess.run(["gsutil", "-q", "-m", "rsync", f"{BK}/tables/launches/", os.path.expanduser("~/.usersim_sim/launches/")])
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.expanduser("~/.usersim_sim/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["id"] = L.id.astype(str); L["daily_rank"] = pd.to_numeric(L.daily_rank, errors="coerce"); L = L[L.daily_rank.notna()]
L["nday"] = L.groupby("day").id.transform("count"); R = L.set_index("id")
rows = []
for f in glob.glob(os.path.join(loc, "*/*.json.gz")):
    r = json.load(gzip.open(f, "rt")); i = r["id"]
    if "fail" in r or i not in R.index or "band_v2" not in r: continue
    v1 = r["band_v1"]; v2 = r["band_v2"]; rk = float(R.daily_rank[i])
    rows.append({"id": i, "day": R.day[i], "rank": rk, "nday": float(R.nday[i]), "hours_after_launch": r.get("hours_after_launch"), "v1": v1["percentile"],
                 "v1_lo": v1["rank_band"]["likely"][0], "v1_hi": v1["rank_band"]["likely"][1], "b0": v2["run2"]["b0_pct"],
                 "v2_run1": v2["run1"]["S_PRIMARY"]["pct"], "v2_run2": v2["run2"]["S_PRIMARY"]["pct"], "facts": v2["run2"]["B0+facts"]["pct"]})
D = pd.DataFrame(rows); res = {"launches": len(D), "days": int(D.day.nunique()) if len(D) else 0}
if len(D) >= 10:
    sp = lambda a, b: spearmanr(a, b).correlation
    for c in ("v1", "b0", "v2_run1", "v2_run2", "facts"): res[c] = round(float(sp(D[c], -D["rank"])), 3)
    n = len(D); Bt = [rng.integers(0, n, n) for _ in range(2000)]
    for c in ("v2_run1", "v2_run2", "facts"):
        ds = [sp(D[c].values[j], -D["rank"].values[j]) - sp(D.v1.values[j], -D["rank"].values[j]) for j in Bt]; res[f"{c} - v1"] = [round(float(x), 3) for x in np.percentile(ds, [2.5, 50, 97.5])]
    res["v1_rank_band_coverage"] = round(float(((D["rank"] >= D.v1_lo) & (D["rank"] <= D.v1_hi)).mean()), 3)
    wd = {c: [sp(g[c], -g["rank"]) for _, g in D.groupby("day") if len(g) >= 5] for c in ("v1", "v2_run1", "v2_run2", "facts")}
    res["within_day_mean"] = {c: round(float(np.nanmean(v)), 3) for c, v in wd.items()}
# URL coverage by final rank group (selection made visible): from the per-day summaries
cov = []
for f in glob.glob(os.path.join(SP, "forward/*_summary.json")) + glob.glob(os.path.join(loc, "*/_summary.json")):
    sm = json.load(open(f))
    for i in sm.get("all_ids", []):
        if i in R.index: cov.append({"g": "1-3" if R.daily_rank[i] <= 3 else "4-10" if R.daily_rank[i] <= 10 else "11+", "has": i in sm.get("url_source_by_id", {})})
if cov: res["url_coverage_by_rank_group"] = pd.DataFrame(cov).drop_duplicates().groupby("g").has.agg(["mean", "size"]).round(3).to_dict("index")
json.dump(res, open(OUT, "w"), indent=1); print(json.dumps(res))
