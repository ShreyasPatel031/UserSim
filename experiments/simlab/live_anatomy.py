"""Live error anatomy of the published 00:05 forecast, Nov 1-4 and 8-12 (orchestrator 01:16Z Nov 14). Counts and launch ids only.
Published picks: results/web/forecast_0005/<day>.json predicted_rank (clean_nosite line); its score (for the pick-3 / pick-4 margin) from
raw/daily/<day>/forecast_<day>.parquet `pred` where that file exists. Truth: official daily_rank (warehouse). Arm 2: PH ops' nov_arm2
'both' (month-fold; built from final-read inputs, so a mild advantage). Per day: the published top 3 vs the official top 3; for every
missed winner: its published rank, first-time hunter (no featured hunt on an earlier day in the 2025 lists / 2026 warehouse), self-hunt
(hunter among named makers); the day's #1 vote share (late votes) and field size; margin pick 3 - pick 4 (z of pred within day); arm 2's
top 3 and its hits. Buckets per missed winner: flat day (#1 share < 0.12), newcomer winner (first-time hunter), published had it at 4-5,
at 6-10, at 11+. Confidence: PH ops' frozen arm-2 top-3 confidence (top3_confidence_arm2_20261113.json) -> expected top-3 hits per day
from arm 2's scores; tiers by the backtest terciles of that expectation (open / normal / sure).
    python live_anatomy.py <scratchpad> <out dir>
"""
import glob, json, os, sys, subprocess
import numpy as np, pandas as pd
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
sys.path.insert(0, "/home/user/UserSim/experiments"); from pipeline import warehouse as W
L = W.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L["votes"] = pd.to_numeric(L.votes, errors="coerce")
def mk(m):
    try: return [str(x).lower() for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
first = {}
for f in glob.glob(f"{SP}/ph2025/*.json"):
    for p in json.load(open(f)):
        u = str((p.get("user") or {}).get("username") or "").lower(); first[u] = min(first.get(u, "9999"), os.path.basename(f)[:10])
for p, d in zip(L.poster.astype(str).str.lower(), L.day): first[p] = min(first.get(p, "9999"), d)
A2 = pd.read_parquet(f"{SP}/a2x/nov_arm2.parquet"); A2["id"] = A2.id.astype(str)
CF = json.loads(subprocess.run(["git", "-C", "/home/user/UserSim", "show", "origin/claude/ph-ops-agent:experiments/ph_predict/results/frozen/top3_confidence_arm2_20261113.json"], capture_output=True, text=True).stdout)
def expected_hits(scores, n):
    s = np.sort(np.asarray(scores, float))[::-1]
    if len(s) < 4: return np.nan
    tot = 0.0
    for k in range(3):
        x = {"pos2": float(k == 1), "pos3": float(k == 2), "m_k4": s[k] - s[3], "m_34": s[2] - s[3], "m_12": s[0] - s[1], "lnn": np.log(n)}
        tot += 1 / (1 + np.exp(-(CF["intercept"] + sum(CF["coef"][f] * x[f] for f in CF["features"]))))
    return tot
X = pd.read_parquet(f"{SP}/a2x/X.parquet"); bt = np.array([expected_hits(g.both.values, len(g)) for _, g in X.groupby("day")]); q1, q2 = np.nanpercentile(bt, [33.3, 66.7])
tier = lambda e: "open" if e < q1 else ("normal" if e < q2 else "sure")
days, rows = [], []
for f in sorted(glob.glob(f"{SP}/f05/*.json")):
    J = json.load(open(f)); d = J["day"]; g = L[(L.day == d) & L.daily_rank.notna()]
    if len(g) < 10: continue
    F = pd.DataFrame(J["forecast"]); F["id"] = F.id.astype(str); F = F[F.id.isin(g.id)]; prank = dict(zip(F.id, F.predicted_rank))
    pub = F.sort_values("predicted_rank").id.tolist(); t3 = g.nsmallest(3, "daily_rank").id.tolist(); hit = len(set(pub[:3]) & set(t3))
    fc = f"{SP}/fc/forecast_{d}.parquet"; mg = np.nan
    if os.path.exists(fc) and os.path.getsize(fc) > 0:
        P = pd.read_parquet(fc); P["id"] = P.id.astype(str); P = P[P.id.isin(g.id)]; z = (P.pred - P.pred.mean()) / (P.pred.std() or 1); s = np.sort(z.values)[::-1]; mg = float(s[2] - s[3]) if len(s) > 3 else np.nan
    a = A2[A2.id.isin(g.id)]; a2top = a.sort_values("both", ascending=False).id.tolist(); a2hit = len(set(a2top[:3]) & set(t3)) if len(a) >= 10 else None
    no1 = float(g.loc[g.daily_rank.idxmin(), "votes"] / g.votes.sum()) if g.votes.sum() > 0 else np.nan
    eh = expected_hits(a.both.values, len(g)) if len(a) >= 10 else np.nan
    days.append({"day": d, "field": len(g), "published hits top3": hit, "arm2 hits top3": a2hit, "#1 vote share": round(no1, 3), "pub margin pick3-pick4 (z)": None if np.isnan(mg) else round(mg, 3),
                 "arm2 expected top-3 hits": None if np.isnan(eh) else round(eh, 2), "arm2 confidence tier": None if np.isnan(eh) else tier(eh),
                 "published top 3": pub[:3], "official top 3": t3, "arm2 top 3": a2top[:3]})
    for i in t3:
        if i in pub[:3]: continue
        r = g[g.id == i].iloc[0]; h = str(r.poster).lower(); pr = prank.get(i)
        rows.append({"day": d, "missed winner id": i, "official rank": int(r.daily_rank), "published rank": None if pr is None else int(pr),
                     "first-time hunter": bool(first.get(h, "9999") >= d), "self-hunt": h in mk(r.makers), "flat day (#1 share < 0.12)": bool(no1 < 0.12),
                     "arm2 had it in top 3": i in a2top[:3]})
    for i in pub[:3]:
        if i not in t3: rows.append({"day": d, "wrong pick id": i, "its official rank": int(g[g.id == i].daily_rank.iloc[0])})
M = pd.DataFrame([r for r in rows if "missed winner id" in r]); DD = pd.DataFrame(days)
def bucket(r):
    p = r["published rank"]; return "4-5" if p and p <= 5 else ("6-10" if p and p <= 10 else "11+ / unranked")
M["published-rank bucket"] = M.apply(bucket, axis=1)
pa = DD.dropna(subset=["arm2 hits top3"]); diff = (pa["arm2 hits top3"] - pa["published hits top3"]).values / 3 * 100
bs = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(4000)]
res = {"design": __doc__.split("\n    python")[0], "days": len(DD), "missed winners": len(M),
       "published top 3 (live clean_nosite) %": round(float(DD["published hits top3"].mean() / 3 * 100), 1),
       "arm 2 (month-fold) on same days %": round(float(pa["arm2 hits top3"].mean() / 3 * 100), 1), "arm2 - published, paired [CI]": [round(float(diff.mean()), 1), round(float(np.percentile(bs, 2.5)), 1), round(float(np.percentile(bs, 97.5)), 1), len(diff)],
       "missed winners: share by bucket": {"flat day": round(float(M["flat day (#1 share < 0.12)"].mean()), 2), "newcomer (first-time hunter)": round(float(M["first-time hunter"].mean()), 2),
            "self-hunt": round(float(M["self-hunt"].mean()), 2), **{f"published had it at {k}": round(float((M["published-rank bucket"] == k).mean()), 2) for k in ("4-5", "6-10", "11+ / unranked")},
            "arm 2 had it in its top 3": round(float(M["arm2 had it in top 3"].mean()), 2)},
       "confidence tiers (arm 2 frozen fit; backtest tercile cut-offs)": {"cut-offs expected hits": [round(float(q1), 2), round(float(q2), 2)],
            "published hits by tier": DD.groupby("arm2 confidence tier")["published hits top3"].agg(["mean", "count"]).round(2).to_dict(orient="index"),
            "arm2 hits by tier": DD.groupby("arm2 confidence tier")["arm2 hits top3"].agg(["mean", "count"]).round(2).to_dict(orient="index")},
       "per day": days, "per miss / wrong pick": rows}
json.dump(res, open(os.path.join(OUT, "live_anatomy.json"), "w"), indent=1, default=str)
for k, v in res.items():
    if k not in ("design", "per miss / wrong pick"): print(k, json.dumps(v, default=str)[:2500])
