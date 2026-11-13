"""Pre-launch / early commenter counts, 2025 vs 2026 (orchestrator 07:34Z Nov 13). No LLM.
th_n_pre (the stack's definition, early_stack.py): distinct commenters other than the hunter with a comment created at or before
00:05 PT of the launch day. Variant th_n_pre_team also drops every listed maker. Early counts n_0030 / n_0100: same, up to 00:30 /
01:00 PT. All counts include replies.
2026 reference: the launch thread dumps (cf/page*.jsonl.gz, comments with exact createdAt and author; page-1 threads, capped), launches
Jan - Oct 2026 with a daily rank. 2025: raw/ph_history/comments_2025/<day>.jsonl (post_id, id, createdAt, parentId, userId; DRAFT)
joined to raw/ph_history/2025/<day>.json (featuredAt, dailyRank, hunter / maker ids). The launch day's 00:00 PT comes from featuredAt.
Data check (2025): createdAt and userId present; rows per post vs the list's commentsCount; share of posts with a comment created
before featuredAt. Outputs: mean, share zero, by final rank (1-3 / 4-10 / 11+), within-day Spearman with -dailyRank (day bootstrap).
Counts only, no ids written.
    python th_2025.py <scratchpad> <out dir>
"""
import glob, gzip, hashlib, json, os, subprocess, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); BK = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_history"
PT = "America/Los_Angeles"; CUTS = {"th_n_pre": 5, "n_0030": 30, "n_0100": 60}
def counts(rows, t0, excl):
    o = {}
    for k, m in CUTS.items():
        lim = t0 + pd.Timedelta(minutes=m); o[k] = len({u for u, t in rows if t <= lim and u not in excl})
    return o
def summarize(D):
    o = {"launches": len(D), "days": int(D.day.nunique())}
    for k in list(CUTS) + ["th_n_pre_team"]:
        if k not in D: continue
        sp = [spearmanr(g[k], -g["rank"]).correlation for _, g in D.groupby("day") if len(g) >= 8 and g[k].nunique() > 1]
        sp = np.array([s for s in sp if s == s]); bs = [sp[rng.integers(0, len(sp), len(sp))].mean() for _ in range(2000)] if len(sp) else [np.nan]
        o[k] = {"mean": round(float(D[k].mean()), 2), "share_zero": round(float((D[k] == 0).mean()), 3),
                "mean_by_rank 1-3 / 4-10 / 11+": [round(float(D[D["rank"] <= 3][k].mean()), 2), round(float(D[(D["rank"] > 3) & (D["rank"] <= 10)][k].mean()), 2), round(float(D[D["rank"] > 10][k].mean()), 2)],
                "within_day_spearman": [round(float(sp.mean()), 3) if len(sp) else None, round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), len(sp)]}
    return o
res = {"design": __doc__.split("\n    python")[0]}
# ---------- 2026 reference ----------
SALT = open(os.path.join(SP, "early/salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna()].copy(); bys = {s: i for i, s in enumerate(L.slug)}; L = L.reset_index(drop=True); bys = {s: i for i, s in enumerate(L.slug)}
def mk(m):
    try: return {pid(x) for x in json.loads(m) if x and not str(x).startswith("[")} if isinstance(m, str) and m.startswith("[") else set()
    except Exception: return set()
hun = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in L.poster]; mks = [mk(m) for m in L.makers]
com = {}
for f in sorted(glob.glob(os.path.join(SP, "cf/page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        i = bys[p_["slug"]]; out = com.setdefault(i, {})
        def walk(n):
            u = ((n.get("user") or {}).get("username") or "").lower(); t = n.get("createdAt")
            if u and t: out[n.get("id")] = (pid(u), pd.Timestamp(t).tz_convert("UTC"))
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
R6 = []
for i in com:
    t0 = pd.Timestamp(L.day.iat[i]).tz_localize(PT, ambiguous=True).tz_convert("UTC"); rows = list(com[i].values())
    o = counts(rows, t0, {hun[i]} - {None}); o["th_n_pre_team"] = counts(rows, t0, ({hun[i]} | mks[i]) - {None})["th_n_pre"]
    o.update({"day": L.day.iat[i], "rank": float(L.daily_rank.iat[i]), "any_before_start": float(any(t < t0 for _, t in rows))}); R6.append(o)
D6 = pd.DataFrame(R6); res["2026"] = summarize(D6); res["2026"]["share_posts_with_comment_before_00:00PT"] = round(float(D6.any_before_start.mean()), 3)
print("2026", json.dumps(res["2026"]), flush=True)
# ---------- 2025 (whatever days have landed) ----------
lsd = subprocess.run(["gsutil", "ls", f"{BK}/comments_2025/"], capture_output=True, text=True).stdout.split()
days = sorted(os.path.basename(p)[:-6] for p in lsd if p.endswith(".jsonl")); res["2025_days_landed"] = days; R5, chk = [], {"rows": 0, "createdAt_missing": 0, "userId_missing": 0, "posts": 0, "posts_rows_vs_commentsCount": []}
for d in days:
    C = [json.loads(l) for l in subprocess.run(["gsutil", "cat", f"{BK}/comments_2025/{d}.jsonl"], capture_output=True).stdout.decode().split("\n") if l.strip()]
    P = json.loads(subprocess.run(["gsutil", "cat", f"{BK}/2025/{d}.json"], capture_output=True).stdout); bp = {}
    for c in C:
        chk["rows"] += 1; chk["createdAt_missing"] += not c.get("createdAt"); chk["userId_missing"] += not c.get("userId")
        if c.get("createdAt") and c.get("userId"): bp.setdefault(str(c["post_id"]), {})[c.get("id")] = (str(c["userId"]), pd.Timestamp(c["createdAt"]).tz_convert("UTC"))
    for p in P:
        if not p.get("dailyRank"): continue
        chk["posts"] += 1; rows = list(bp.get(str(p["id"]), {}).values()); fe = pd.Timestamp(p["featuredAt"]).tz_convert("UTC")
        t0 = fe.tz_convert(PT).normalize().tz_convert("UTC"); h = str((p.get("user") or {}).get("id")); m = {str(x.get("id")) for x in p.get("makers") or []}
        if p.get("commentsCount"): chk["posts_rows_vs_commentsCount"].append(len(bp.get(str(p["id"]), {})) / p["commentsCount"])
        o = counts(rows, t0, {h}); o["th_n_pre_team"] = counts(rows, t0, {h} | m)["th_n_pre"]
        o.update({"day": d, "rank": float(p["dailyRank"]), "any_before_featured": float(any(t < fe for _, t in rows))}); R5.append(o)
if R5:
    D5 = pd.DataFrame(R5); res["2025"] = summarize(D5); res["2025"]["share_posts_with_comment_before_featuredAt"] = round(float(D5.any_before_featured.mean()), 3)
    r = np.array(chk.pop("posts_rows_vs_commentsCount")); chk["rows_over_commentsCount median / share >= 0.95"] = [round(float(np.median(r)), 3), round(float((r >= 0.95).mean()), 3)] if len(r) else None
    res["2025_data_check"] = chk
json.dump(res, open(os.path.join(OUT, "th_2025.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float)[:2500])
