"""reviewsCount at the 00:01 PT read vs final rank and vs the clean model's residual (orchestrator 17:34Z Nov 12; counts only).
Per live day: posts_ts rows fetched <= 00:06 PT (official API), reviews_count / reviews_rating at the first such read.
Clean score: results/clean_live_rows_nosite.parquet clean_v3 (as-live, 00:05 inputs). Residual = within-day rank of the final
daily rank minus the within-day rank of the clean score (positive = finished better than the clean model said).
usage: python reviews_check.py -> results/reviews_check.md"""
import json, os, re, subprocess, sys, tempfile
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
CL = pd.read_parquet(os.path.join(HERE, "results", "clean_live_rows_nosite.parquet")); CL["id"] = CL.id.astype(str)
rows = []
for d in sorted(CL.day.unique()):
    p = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/tmp")) + "/p.jsonl"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{d}/live/posts_ts.jsonl", p], stderr=subprocess.DEVNULL).returncode:
        continue
    cut = pd.Timestamp(d + " 00:06", tz="America/Los_Angeles").tz_convert("UTC"); first = {}
    for l in open(p):
        r = json.loads(l)
        if r.get("fetch_status") != 200 or not str(r.get("source", "")).startswith("ph_api_v2") or r.get("reviews_count") is None:
            continue
        fa = pd.Timestamp(r.get("fetched_at") or r["snapshot_ts"])
        if fa <= cut and (str(r["launch_id"]) not in first or fa < first[str(r["launch_id"])][0]):
            first[str(r["launch_id"])] = (fa, float(r["reviews_count"]), r.get("reviews_rating"), str(r.get("slug") or ""))
    g = CL[(CL.day == d) & CL["rank"].notna()]
    for i, rk, sc in zip(g.id, g["rank"], g.clean_v3):
        if i in first:
            fa, rc, rt, sl = first[i]
            m = re.search(r"-(\d+)$", sl)
            rows.append({"day": d, "id": i, "rank": rk, "clean": sc, "rev": rc, "rating": float(rt) if rt not in (None, "") else np.nan,
                         "relaunch": float(bool(m))})
X = pd.DataFrame(rows)
X["r_final"] = X.groupby("day")["rank"].rank(); X["r_clean"] = X.groupby("day").clean.rank(ascending=False)
X["resid"] = X.r_clean - X.r_final; X["has"] = (X.rev > 0).astype(float); X["lrev"] = np.log1p(X.rev)
rng = np.random.default_rng(0); days = sorted(X.day.unique())
def per_day(a, b):
    out = []
    for d in days:
        g = X[X.day == d].dropna(subset=[a, b])
        if len(g) >= 5 and g[a].nunique() > 1:
            out.append(spearmanr(g[a], g[b]).correlation)
    return np.array(out)
md = [f"# reviewsCount at the 00:01 PT read (live days {days[0]}..{days[-1]}: {len(days)} days, {len(X)} launches)", "",
      f"has reviews: {X.has.mean():.1%} of launches; relaunch slug (-N): {X.relaunch.mean():.1%}; corr(has_reviews, relaunch) = {X[['has','relaunch']].corr().iloc[0,1]:.2f}", "",
      "Mean within-day Spearman (day bootstrap 95%), days used. 'vs final' uses -rank (positive = better finish):", "", "| feature | vs final rank | vs clean residual |", "|---|---|---|"]
X["neg_rank"] = -X["rank"]
for f in ("lrev", "has", "rating", "relaunch"):
    cells = []
    for tgt in ("neg_rank", "resid"):
        v = per_day(f, tgt)
        if len(v):
            b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(3000)]
            cells.append(f"{v.mean():+.3f} [{np.percentile(b, 2.5):+.3f}, {np.percentile(b, 97.5):+.3f}] (n {len(v)})")
        else:
            cells.append("-")
    md.append(f"| {f} | {cells[0]} | {cells[1]} |")
open(os.path.join(HERE, "results", "reviews_check.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))
