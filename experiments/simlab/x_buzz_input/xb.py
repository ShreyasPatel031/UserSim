"""Does pre-launch X buzz add to the midnight forecast? (orchestrator 10:34Z Nov 17). Counts and launch ids only.
    python xb.py <scratchpad>   (files staged in <SP>/xb by the README's gsutil lines)
Truth: warehouse launches.daily_rank (final), latest row per id, days with >= 10 ranked.
Lines per final day:
  grok_0030      Grok Bot's frozen top 10 (results/grok_forecast/<d>_0030.json), slug -> id via that day's today_0005 line-up
  grok_0200      same at 02:00 (uses posts to 02:00 PT: NOT a midnight input; shown for reference)
  arm2_pub       published 00:05 arm-2 prediction (raw/daily/<d>/forecast_<d>.parquet 'pred')
  arm3_live      results/shadow_arm3/<d>.json (only Nov 16 final)
  prereveal      results/web/predictions/<d>_prereveal.json (03:45 PT, hybrid_vm)
  buzz_adj       arm2_pub + b1*log1p(pre-launch posts) + b2*missing, b fitted leave-one-day-out on the other buzz days
                 (day-centred residual of log1p(final votes) on the two inputs; ridge 1.0)
Buzz source per day: live x_buzz_0010.jsonl window 'pre_launch' (48 h to 00:00 PT) where it exists (Nov 13, 15, 16), else the
x_buzz_backfill.jsonl 'pre_post_count' (same 48 h window, searched afterwards on Nov 15; flagged 'backfill'). Launch-day 00:00-00:21
counts are kept separate and NOT used in buzz_adj (window ends after 00:15)."""
import glob, json, os, re, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from pipeline import warehouse as W
SP = sys.argv[1]; X = f"{SP}/xb"; rng = np.random.default_rng(0)
L = W.table("launches", do_sync=True).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L["day"] = L.day.astype(str)
COLL = r"generic|collision|ambig|common word|unrelated|cannot distinguish"
DAYS = [f"2026-11-{d:02d}" for d in range(8, 17)]
out = {"days": {}, "notes": []}

def lineup(d):
    j = json.load(open(f"{X}/today_{d}.json")); return {r["slug"]: str(r["id"]) for r in j}, {r["name"].strip().lower(): str(r["id"]) for r in j}, [str(r["id"]) for r in j]

def buzz(d):
    slug2id, name2id, ids = lineup(d); rows = {}
    live = f"{X}/{d}_x_buzz_0010.jsonl"; bf = f"{X}/{d}_x_buzz_backfill.jsonl"
    if os.path.exists(live) and os.path.getsize(live) > 300:
        src = "live_0010"
        for ln in open(live):
            r = json.loads(ln); i = slug2id.get(r.get("slug")) or name2id.get(str(r.get("name", "")).strip().lower())
            if not i: continue
            key = ("pre" if r["window"] == "pre_launch" else "day") if "window" in r else ("pre" if pd.Timestamp(r["window_end"]) <= pd.Timestamp(d + " 08:00", tz="UTC") else "day")
            rows.setdefault(i, {})[key] = r.get("post_count"); rows[i][key + "_lb"] = r.get("post_count_is_lower_bound"); rows[i]["fetched_at"] = r.get("fetched_at")
            if re.search(COLL, str(r.get("notes", "")), re.I): rows[i]["collision"] = 1
        if not any("pre" in v for v in rows.values()):   # Nov 13: one mixed window 48 h to 00:17 PT -> not pre-launch only; use the backfill pre count
            out["notes"].append(f"{d}: live 00:10 file has one window ending after 00:00 PT (mixed); pre-launch count taken from backfill"); live_rows = rows; rows = {}
            for ln in open(bf):
                r = json.loads(ln); i = str(r.get("launch_id") or slug2id.get(r.get("slug")) or "")
                if i: rows[i] = {"pre": r.get("pre_post_count"), "collision": live_rows.get(i, {}).get("collision", 0)}
            src = "backfill (live mixed)"
    elif os.path.exists(bf) and os.path.getsize(bf) > 300:
        src = "backfill"
        for ln in open(bf):
            r = json.loads(ln); i = str(r.get("launch_id") or slug2id.get(r.get("slug")) or "")
            if not i: continue
            rows[i] = {"pre": r.get("pre_post_count"), "pre_lb": r.get("pre_post_count_is_lower_bound"), "fetched_at": r.get("fetched_at")}
    else: return None, None, ids
    b = pd.DataFrame([{"id": i, **rows.get(i, {})} for i in ids])
    if "collision" not in b: b["collision"] = 0
    b["missing"] = (b["pre"].isna() | (b["collision"].fillna(0) == 1)).astype(int)
    return src, b, ids

def grok(d, pt):
    f = f"{X}/{d}_{pt}.json"
    if not os.path.exists(f): return None
    slug2id, name2id, _ = lineup(d); j = json.load(open(f))
    return [slug2id.get(r.get("slug")) or name2id.get(str(r.get("name", "")).strip().lower()) for r in sorted(j["forecast"], key=lambda r: r["rank"])], j.get("written_at")

def hits(order, truth, k): return len(set([o for o in order[:k] if o]) & set(truth[truth.daily_rank <= k].id)) / k * 100

frames = []
for d in DAYS:
    T = L[(L.day == d) & L.daily_rank.notna()][["id", "daily_rank", "votes"]]
    if len(T) < 10: continue
    fp = f"{SP}/wm/fc/forecast_{d}.parquet"
    if not os.path.exists(fp): continue
    P = pd.read_parquet(fp, columns=["id", "pred"]); P["id"] = P.id.astype(str)
    src, b, ids = buzz(d)
    D = P.merge(T, on="id", how="inner")
    if b is not None: D = D.merge(b, on="id", how="left")
    D["day"] = d; D["src"] = src; frames.append(D)
    lines = {"arm2_pub": D.sort_values("pred", ascending=False).id.tolist()}
    for pt in ("0030", "0200"):
        g = grok(d, pt)
        if g: lines[f"grok_{pt}"] = g[0]
    if os.path.exists(f"{X}/arm3_{d}.json"): lines["arm3_live"] = [r["id"] for r in json.load(open(f"{X}/arm3_{d}.json"))["ranking"]]
    if os.path.exists(f"{X}/prereveal_{d}.json"): lines["prereveal"] = [r["id"] for r in json.load(open(f"{X}/prereveal_{d}.json"))["ranking"]]
    out["days"][d] = {"ranked": int(len(T)), "lineup_0005": len(ids), "buzz_src": src,
                      "lines": {k: [hits(v, T, kk) for kk in (3, 5, 10)] for k, v in lines.items()}}
    if b is not None:
        out["days"][d]["buzz_rows"] = int((b.missing == 0).sum()); out["days"][d]["buzz_missing"] = int(b.missing.sum())
        out["days"][d]["grok_unmatched_ids"] = {pt: sum(1 for x in (grok(d, pt) or ([],))[0] if not x) for pt in ("0030", "0200")}

F = pd.concat(frames); F["y"] = np.log1p(F.votes.astype(float))
F["res"] = (F.y - F.groupby("day").y.transform("mean")) - (F.pred - F.groupby("day").pred.transform("mean"))
BZ = F[F.src.notna()].copy(); BZ["lb"] = np.log1p(BZ.pre.fillna(0).astype(float)); BZ["missing"] = BZ.missing.fillna(1)
for c in ("lb", "missing"): BZ[c + "_c"] = BZ[c] - BZ.groupby("day")[c].transform("mean")
# signal checks (pooled, launch-level; day bootstrap)
def boot_stat(f):
    days = BZ.day.unique(); v = []
    for _ in range(2000):
        s = rng.choice(days, len(days)); g = pd.concat([BZ[BZ.day == x] for x in s]); v.append(f(g))
    return [round(float(f(BZ)), 3), round(float(np.nanpercentile(v, 2.5)), 3), round(float(np.nanpercentile(v, 97.5)), 3)]
pres = lambda g: g[g.missing == 0]
out["signal"] = {
    "launches_with_buzz_day": int(len(BZ)), "buzz_days": sorted(BZ.day.unique().tolist()),
    "spearman(log posts, residual of arm2_pub) among present": boot_stat(lambda g: pres(g).lb.corr(pres(g).res, method="spearman")),
    "spearman(log posts, final votes day-centred) among present": boot_stat(lambda g: pres(g).lb.corr(pres(g).y - pres(g).groupby('day').y.transform('mean'), method="spearman")),
    "mean residual missing minus present": boot_stat(lambda g: g[g.missing == 1].res.mean() - g[g.missing == 0].res.mean()),
    "share missing": round(float(BZ.missing.mean()), 3)}
# leave-one-day-out adjusted line
adj = []
for d in BZ.day.unique():
    tr = BZ[BZ.day != d]; A = np.c_[tr.lb_c, tr.missing_c]; beta = np.linalg.solve(A.T @ A + np.eye(2), A.T @ tr.res.values)
    te = BZ[BZ.day == d].copy(); te["adj"] = te.pred + beta[0] * te.lb + beta[1] * te.missing; te["b1"], te["b2"] = beta; adj.append(te)
A = pd.concat(adj); rows = []
for d, g in A.groupby("day"):
    T = g[["id", "daily_rank"]]
    r = {"day": d, **{f"base_top{k}": hits(g.sort_values("pred", ascending=False).id.tolist(), T, k) for k in (3, 5, 10)},
         **{f"adj_top{k}": hits(g.sort_values("adj", ascending=False).id.tolist(), T, k) for k in (3, 5, 10)}, "b1": round(g.b1.iloc[0], 3), "b2": round(g.b2.iloc[0], 3)}
    rows.append(r); out["days"][d]["lines"]["buzz_adj (LODO)"] = [r[f"adj_top{k}"] for k in (3, 5, 10)]
R = pd.DataFrame(rows); out["buzz_adj_paired"] = {"n_days": int(len(R))}
for k in (3, 5, 10):
    v = (R[f"adj_top{k}"] - R[f"base_top{k}"]).values; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    out["buzz_adj_paired"][f"top{k}"] = [round(v.mean(), 1), round(np.percentile(bs, 2.5), 1), round(np.percentile(bs, 97.5), 1)]
out["buzz_adj_paired"]["coef_by_held_day"] = R[["day", "b1", "b2"]].to_dict("records")
# same-day comparison table (days where a line exists), mean hits
tab = {}
for ln in ("grok_0030", "grok_0200", "arm2_pub", "arm3_live", "prereveal", "buzz_adj (LODO)"):
    ds = [d for d in out["days"] if ln in out["days"][d]["lines"]]
    tab[ln] = {"days": ds, "mean top3/5/10": [round(np.mean([out["days"][d]["lines"][ln][i] for d in ds]), 1) for i in range(3)] if ds else None}
out["lines_mean"] = tab
json.dump(out, open(os.path.join(HERE, "result.json"), "w"), indent=1, default=str); print(json.dumps(out, indent=1, default=str))
