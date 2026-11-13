"""Score Grok Bot's pre-launch X-buzz count against final daily rank (orchestrator 08:34Z Nov 13). No LLM.
Buzz: raw/ph_at_launch/<day>/x_buzz_backfill.jsonl if present, else x_buzz_0010.jsonl (post_count in the 48 h before launch; slug-keyed,
mapped to launch ids by the 00:05 read / warehouse launches). Missing launches count as 0 posts (reported).
Base: clean_v3_nosite (PH agent clean_live_rows_nosite.parquet, origin/claude/ph-ops-agent) where the day is held, else the deployed
00:05 pred (raw/daily/<day>/forecast_<day>.parquet), labelled. th_n_pre is not held for these days. Final rank: warehouse launches
(daily_rank, synced), fallback the clean rows' rank.
Per day: Spearman(log1p posts, -rank); partial beyond the base (within-day rank residuals); top 3/5/10 of base vs base + w z(log1p
posts) (w leave-day-out from {0, .25, .5, 1, 2} by mean top3+top5 on the other days; with one day, every w is shown) vs RULE_t (launches
with posts >= t first by count, the rest by base; t fixed at 100 and 1,000); blind spot = launches the base ranks outside its top 5
that finish top 3, and how many of them buzz flags (>= 100 / >= 1,000 posts). Paired day bootstrap when >= 3 days.
    python xbuzz_score.py <scratchpad> <out dir> <day> [<day> ...]
"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
SP, OUT = sys.argv[1:3]; DAYS = sys.argv[3:]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse  # noqa: E402
BK = "gs://usersim-bakeoff-347838016394/usersim_sim/raw"; gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
WL = warehouse.table("launches", do_sync=True); WL["id"] = WL.id.astype(str); WL = WL.sort_values("updated_at").drop_duplicates("id", keep="last")
CN = pd.read_parquet(os.path.join(SP, "clean_live_rows_nosite.parquet")); CN["id"] = CN.id.astype(str)
z = lambda s: (s - s.mean()) / (s.std() or 1)
def load(day):
    raw = gcat(f"{BK}/ph_at_launch/{day}/x_buzz_backfill.jsonl") or gcat(f"{BK}/ph_at_launch/{day}/x_buzz_0010.jsonl"); src = "backfill" if gcat(f"{BK}/ph_at_launch/{day}/x_buzz_backfill.jsonl") else "0010"
    bz = {}
    for l in raw.decode().split("\n"):
        if l.strip(): x = json.loads(l); bz[str(x.get("slug"))] = x.get("post_count")
    try: lu = {str(x["slug"]): str(x["id"]) for x in json.loads(gcat(f"{BK}/daily/{day}/today_0005.json"))}
    except Exception: lu = {}
    w = WL[WL.day == day]; lu.update({str(s): i for s, i in zip(w.slug, w.id)}); slug_of = {v: k for k, v in lu.items()}
    c = CN[(CN.day == day) & CN.clean_v3_nosite.notna()][["id", "clean_v3_nosite", "rank"]].rename(columns={"clean_v3_nosite": "base"}); base_src = "clean_v3_nosite"
    if c.empty:
        f = os.path.join(SP, f"fc_{day}.parquet"); open(f, "wb").write(gcat(f"{BK}/daily/{day}/forecast_{day}.parquet"))
        c = pd.read_parquet(f)[["id", "pred"]].rename(columns={"pred": "base"}); c["id"] = c.id.astype(str); c["rank"] = np.nan; base_src = "deployed 00:05 pred"
    rk = dict(zip(w.id, w.daily_rank)); c["rank"] = [rk.get(i) if rk.get(i) == rk.get(i) and rk.get(i) is not None else r for i, r in zip(c.id, c["rank"])]
    c["posts"] = [bz.get(slug_of.get(i)) for i in c.id]; miss = int(c.posts.isna().sum()); c["posts"] = c.posts.fillna(0).astype(float)
    c = c[c["rank"].notna()].copy(); c["day"] = day
    return c, {"buzz_file": src, "base": base_src, "launches_scored": len(c), "buzz_missing_as_0": miss, "buzz_rows": len(bz)}
def ov(order, g, k): t = g.sort_values("rank").id.tolist()[:k]; return len(set(order[:k]) & set(t)) / k * 100
def rule(g, t):
    a = g[g.posts >= t].sort_values("posts", ascending=False).id.tolist(); return a + g[g.posts < t].sort_values("base", ascending=False).id.tolist()
D, meta = [], {}
for d in DAYS:
    c, m = load(d); meta[d] = m
    if len(c) >= 8: D.append(c)
res = {"design": __doc__.split("\n    python")[0], "days": meta}
if D:
    A = pd.concat(D); A["zb"] = A.groupby("day").base.transform(z); A["zx"] = A.groupby("day").posts.transform(lambda s: z(np.log1p(s)))
    W = (0, .25, .5, 1, 2); per = {}
    for d, g in A.groupby("day"):
        y = -g["rank"].to_numpy(); r = lambda a: pd.Series(a).rank().to_numpy()
        ry, rb, rx = r(y), r(g.base.to_numpy()), r(np.log1p(g.posts.to_numpy()))
        part = float(np.corrcoef(ry - np.polyval(np.polyfit(rb, ry, 1), rb), rx - np.polyval(np.polyfit(rb, rx, 1), rb))[0, 1]) if g.posts.nunique() > 1 else np.nan
        top = {"base": g.sort_values("base", ascending=False).id.tolist()}
        for w in W: top[f"w{w}"] = g.assign(s=g.zb + w * g.zx).sort_values("s", ascending=False).id.tolist()
        for t in (100, 1000): top[f"rule{t}"] = rule(g, t)
        b5 = set(top["base"][:5]); blind = g[(g["rank"] <= 3) & (~g.id.isin(b5))]
        per[d] = {"spearman_buzz": round(float(spearmanr(np.log1p(g.posts), y).correlation), 3) if g.posts.nunique() > 1 else None, "spearman_base": round(float(spearmanr(g.base, y).correlation), 3),
                  "partial_buzz_beyond_base": round(part, 3) if part == part else None, "top3/5/10": {k: [ov(o, g, kk) for kk in (3, 5, 10)] for k, o in top.items()},
                  "blind_spot_top3_outside_base_top5": len(blind), "flagged_by_buzz >=100 / >=1000": [int((blind.posts >= 100).sum()), int((blind.posts >= 1000).sum())],
                  "launches_with_posts >=100 / >=1000": [int((g.posts >= 100).sum()), int((g.posts >= 1000).sum())]}
    res["per_day"] = per; ds = sorted(per)
    if len(ds) >= 2:   # leave-day-out w
        sel = {}
        for d in ds:
            oth = [x for x in ds if x != d]; sc = {w: np.mean([sum(per[x]["top3/5/10"][f"w{w}"][:2]) for x in oth]) for w in W}; sel[d] = max(sc, key=sc.get)
        res["lodo_w"] = sel
        def diff(key_fn):
            a = np.array([np.array(per[d]["top3/5/10"][key_fn(d)]) - np.array(per[d]["top3/5/10"]["base"]) for d in ds])
            if len(a) < 3: return a.mean(0).round(1).tolist()
            bs = np.array([a[rng.integers(0, len(a), len(a))].mean(0) for _ in range(2000)]); return [[round(float(a[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
        res["gain vs base top3/5/10"] = {"base + buzz (lodo w)": diff(lambda d: f"w{sel[d]}"), "rule100": diff(lambda d: "rule100"), "rule1000": diff(lambda d: "rule1000")}
        res["partial_mean"] = round(float(np.nanmean([per[d]["partial_buzz_beyond_base"] or np.nan for d in ds])), 3)
# days needed for a 5-point top-3 gain: paired per-day top-3 differences move in steps of 33.3; per-day sd about 16 (pairwise_base / hidden_window paired
# top-3 diffs over 14 days); n = ((1.96 + 0.84) * sd / 5)^2
sd = 16.0; res["days_needed_top3_gain_5pts"] = {"assumed_per_day_sd": sd, "n_days": int(np.ceil(((1.96 + 0.84) * sd / 5) ** 2)), "note": "two-sided 5%, 80% power; a 10-point gain needs about a quarter of that"}
json.dump(res, open(os.path.join(OUT, "xbuzz_score.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float)[:3000])
