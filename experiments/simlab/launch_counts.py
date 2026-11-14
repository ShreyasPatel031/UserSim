"""Launch-time audience counts read at the start of the day (orchestrator 01:48Z Nov 14). Counts only; direction only.
Per launch on live days Nov 3-12 (final ranks known), reads strictly before 01:00 PT:
  hunter_followers     raw/daily/<d>/today_0005.json user.followersCount (file written ~00:06 PT)
  team_followers       sum of makers[].followersCount in the same file (hunter counted once)
  team_following       sum of 'following' over the launch's team in raw/ph_at_launch/<d>/makers_header.jsonl, rows fetched < 01:00 PT
  reviews_count / reviews_rating   raw/ph_at_launch/<d>/live/products_ts.jsonl, earliest read, kept only if fetched < 01:00 PT
  (product followers: null in every products_ts row - not captured)
Metrics: within-day Spearman of log1p(count) with final rank (sign: + = more -> better rank); within-day Spearman with the residual of the
published 00:05 forecast (results/web/forecast_0005 predicted_rank - final rank) and of arm 2 (nov_arm2 'both' rank - final rank); day
bootstrap. Add-on: rank-average arm 2 with the count, weight leave-one-day-out, top 3/5/10 vs arm 2 paired.
    python launch_counts.py <scratchpad> <out dir>
"""
import glob, json, os, subprocess, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); PT = "America/Los_Angeles"; rng = np.random.default_rng(0)
sys.path.insert(0, "/home/user/UserSim/experiments"); from pipeline import warehouse as W
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
L = W.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); RK = {i: r for i, r in zip(L.id, L.daily_rank) if pd.notna(r)}
A2 = pd.read_parquet(f"{SP}/a2x/nov_arm2.parquet"); A2["id"] = A2.id.astype(str); PR = dict(zip(A2.id, A2.both))
DAYS = [f"2026-11-{x:02d}" for x in range(3, 13)]; rows = []; qual = {}
def ev(x):
    if isinstance(x, (dict, list)): return x
    try: return json.loads(x)
    except Exception:
        import ast
        try: return ast.literal_eval(x)
        except Exception: return None
for d in DAYS:
    cut = pd.Timestamp(d, tz=PT) + pd.Timedelta(hours=1)
    LU = json.loads(gcat(f"{B}/raw/daily/{d}/today_0005.json") or b"[]")
    MH = [json.loads(l) for l in gcat(f"{B}/raw/ph_at_launch/{d}/makers_header.jsonl").decode().splitlines() if l.strip()]
    MH = [m for m in MH if m.get("fetched_at") and pd.Timestamp(m["fetched_at"]) < cut]; fol = {}
    for m in MH:
        for s in m.get("posts") or []: fol.setdefault(s, []).append(m.get("following") or 0)
    PTS = [json.loads(l) for l in gcat(f"{B}/raw/ph_at_launch/{d}/live/products_ts.jsonl").decode().splitlines() if l.strip()]
    PTS = sorted([p for p in PTS if pd.Timestamp(p["fetched_at"]) < cut], key=lambda p: p["fetched_at"]); rv = {}
    for p in PTS: rv.setdefault(p["product_slug"], p)
    for x in LU:
        u = ev(x.get("user")) or {}; mk = ev(x.get("makers")) or []
        tf = {m.get("username"): m.get("followersCount") or 0 for m in mk if isinstance(m, dict)}; tf[u.get("username")] = u.get("followersCount") or 0
        r = rv.get(x.get("slug"))
        rows.append({"day": d, "id": str(x["id"]), "hunter_followers": u.get("followersCount"), "team_followers": sum(v or 0 for v in tf.values()),
                     "team_following": sum(fol.get(x.get("slug"), [])) if x.get("slug") in fol else np.nan,
                     "reviews_count": r.get("reviews_count") if r else np.nan, "reviews_rating": r.get("reviews_rating") if r else np.nan})
    qual[d] = {"launches": len(LU), "makers_header rows < 01:00": len(MH), "products_ts reads < 01:00": len(rv)}
X = pd.DataFrame(rows); X = X[X.id.isin(RK)].copy(); X["rank"] = X.id.map(RK).astype(float)
F05 = {}
for d in DAYS:
    j = json.loads(gcat(f"{B}/results/web/forecast_0005/{d}.json") or b"{}"); F05.update({str(r["id"]): r["predicted_rank"] for r in j.get("forecast") or []})
X["pub_res"] = X.id.map(F05) - X["rank"]; X["a2"] = X.id.map(PR); X["a2_res"] = X.groupby("day").a2.rank(ascending=False) - X["rank"]
FE = ["hunter_followers", "team_followers", "team_following", "reviews_count", "reviews_rating"]
def dboot(fn, col, target):
    def per(g): g = g.dropna(subset=[col, target]); return spearmanr(np.log1p(g[col].astype(float)), g[target]).correlation if len(g) >= 6 and g[col].nunique() > 1 else np.nan
    v = np.array([per(g) for _, g in X.groupby("day")]); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [np.mean(v[rng.integers(0, len(v), len(v))]) for _ in range(2000)]; return [round(float(v.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), len(v)]
X["neg_rank"] = -X["rank"]
res = {"design": __doc__.split("\n    python")[0], "qualifying reads per day": qual, "launches with final rank": len(X),
       "coverage (share non-null)": {f: round(float(X[f].notna().mean()), 3) for f in FE}}
for f in FE:
    res[f] = {"Spearman with final rank (+ = more -> better)": dboot(None, f, "neg_rank"), "with published 00:05 residual (+ = count predicts finishing above the forecast)": dboot(None, f, "pub_res"),
              "with arm-2 residual": dboot(None, f, "a2_res")}
best = max(FE, key=lambda f: (res[f]["with arm-2 residual"] or [0])[0])
def hits(s, g): o = g.assign(s=s).sort_values("s").id.tolist(); t = g.sort_values("rank").id.tolist(); return np.array([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
G = {d: g.dropna(subset=["a2"]).copy() for d, g in X.groupby("day")}; G = {d: g for d, g in G.items() if len(g) >= 10}
for g in G.values(): g["ra"] = g.a2.rank(ascending=False); g["rc"] = np.log1p(g[best].fillna(0).astype(float)).rank(ascending=False)
WS = np.round(np.arange(0, 1.01, .1), 1); dd = sorted(G); sc = lambda w, d: hits((1 - w) * G[d].ra + w * G[d].rc + rng.random(len(G[d])) * 1e-6, d and G[d])
A = np.array([sc(0, d) for d in dd]); LO = []
for d in dd:
    tr = [x for x in dd if x != d]; w = max(WS, key=lambda w: np.mean([sc(w, x).mean() for x in tr])); LO.append(sc(w, d))
LO = np.array(LO); D_ = LO - A; bs = np.array([D_[rng.integers(0, len(D_), len(D_))].mean(0) for _ in range(4000)])
res[f"add-on to arm 2: {best} (LODO weight)"] = {"days": len(dd), "arm 2 top3/5/10": A.mean(0).round(1).tolist(), "blend": LO.mean(0).round(1).tolist(),
    "blend - arm 2 [CI]": [[round(float(D_[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]}
json.dump(res, open(os.path.join(OUT, "launch_counts.json"), "w"), indent=1, default=float)
for k, v in res.items():
    if k != "design": print(k, json.dumps(v, default=float)[:900])
# signed add-on (residual correlations are negative: arm 2 already over-ranks high-follower teams) - penalty form, LODO
for f in ("team_followers", "hunter_followers", "team_following"):
    for g in G.values(): g["rf"] = np.log1p(g[f].fillna(0).astype(float)).rank(ascending=False)
    WP = [0, .05, .1, .2, .3]; sp = lambda w, d: hits(G[d].ra - w * (G[d].rf - G[d].rf.mean()) * -1 + rng.random(len(G[d])) * 1e-6, G[d])
    # score = ra + w * (rf - mean): a higher follower rank number (fewer followers) is pushed up less; i.e. many followers are penalised
    sp = lambda w, d: hits(G[d].ra + w * ((len(G[d]) + 1) - G[d].rf - (len(G[d]) + 1) / 2) + rng.random(len(G[d])) * 1e-6, G[d])
    A0 = np.array([sp(0, d) for d in dd]); LO2, wl = [], []
    for d in dd:
        tr = [x for x in dd if x != d]; w = max(WP, key=lambda w: np.mean([sp(w, x).mean() for x in tr])); wl.append(w); LO2.append(sp(w, d))
    D2 = np.array(LO2) - A0; bs2 = np.array([D2[rng.integers(0, len(D2), len(D2))].mean(0) for _ in range(4000)])
    res[f"penalty on {f} (LODO)"] = {"weights": wl, "blend - arm 2 [CI]": [[round(float(D2[:, j].mean()), 1), round(float(np.percentile(bs2[:, j], 2.5)), 1), round(float(np.percentile(bs2[:, j], 97.5)), 1)] for j in range(3)]}
    print(f"penalty on {f}", json.dumps(res[f"penalty on {f} (LODO)"]))
json.dump(res, open(os.path.join(OUT, "launch_counts.json"), "w"), indent=1, default=float)
