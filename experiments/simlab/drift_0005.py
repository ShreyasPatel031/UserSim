"""Accuracy drift of the 00:05 model (orchestrator 01:08Z Nov 14). Counts only.
(1) Top 3/5/10 by calendar month Apr-Oct: arm 2 (PH ops dump, walk-forward fold) and clean_nosite (tw_nosite clean_v3_nosite), paired
    difference per month (day bootstrap); trend = OLS slope of daily top-3 hits on day index (per 30 days), bootstrap interval.
(2) Daily covariates: launches per day; share of the true top 3 that are first-time hunters (first_hunter.py definition) and self-hunts
    (hunter among named makers); share of the true top 3 whose hunter hunted in 2025; hunter-record coverage (share with hist_hunter_n > 0);
    #1 vote share (late votes of rank 1 / day total); AI share (topic_is_ai); video-first share (first media item is a video, PH ops day files).
    Monthly means; OLS of daily arm-2 top-3 hits on the standardized covariates (day bootstrap intervals).
(3) Recency proxy: LightGBM on arm 2's 40 inputs trained on 2026 rows only (Apr+), month-forward, target = day-demeaned log1p late votes,
    3 seeds; rows dated in the 60 days before the test month weighted x1 / x2 / x3; scored on Sep and Oct. NOT arm 2 itself (arm 2 trains
    on 2025 + 2026 with PH ops' data dir); differences between weightings are the readable part.
(4) Live check: published 00:05 files (results/web/forecast_0005, clean_nosite line) for Nov 1-13 vs official daily_rank.
    python drift_0005.py <scratchpad> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
import lightgbm as lgb
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
sys.path.insert(0, "/home/user/UserSim/experiments"); from pipeline import warehouse as W
X = pd.read_parquet(f"{SP}/a2x/X.parquet"); X["id"] = X.id.astype(str); INP = json.load(open(f"{SP}/a2x/cols.json"))["2026-04"]
TW = pd.read_parquet(f"{SP}/tw_nosite.parquet")[["id", "clean_v3_nosite"]]; TW["id"] = TW.id.astype(str); X = X.merge(TW, on="id", how="left")
L = W.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
L["votes"] = pd.to_numeric(L.votes, errors="coerce")
def mk(m):
    try: return [str(x).lower() for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
L["selfhunt"] = [str(p).lower() in mk(m) for p, m in zip(L.poster, L.makers)]
h25 = set()
for f in glob.glob(f"{SP}/ph2025/*.json"):
    for p in json.load(open(f)): h25.add(str((p.get("user") or {}).get("username") or "").lower())
L["h25"] = L.poster.astype(str).str.lower().isin(h25)
FT = pd.read_parquet(f"{SP}/stack/fth.parquet")[["id", "fth"]]; FT["id"] = FT.id.astype(str)
vid = {}
for f in glob.glob(f"{SP}/grow/days/*.json"):
    for p in json.load(open(f)):
        md = p.get("media") or []; t = (md[0].get("type") if md and isinstance(md[0], dict) else None)
        vid[str(p["id"])] = float(str(t).lower() == "video")
X = X.merge(L[["id", "votes", "selfhunt", "h25"]], on="id", how="left").merge(FT, on="id", how="left"); X["vidfirst"] = X.id.map(vid)
X["mon"] = X.day.str[:7]; X["rank"] = X.dailyRank.astype(float)
def dm(g, col):
    o = g.sort_values([col, "id"], ascending=[False, True]).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def ci(A):
    A = np.asarray(A, float); A = A.reshape(len(A), -1); bs = np.array([A[rng.integers(0, len(A), len(A))].mean(0) for _ in range(4000)])
    return [[round(float(A[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(A.shape[1])]
days = sorted(X.day.unique()); A2 = {d: dm(X[X.day == d], "both") for d in days}; CN = {d: dm(X[X.day == d].dropna(subset=["clean_v3_nosite"]), "clean_v3_nosite") for d in days}
res = {"design": __doc__.split("\n    python")[0], "(1) by month": {}}
for m in sorted(X.mon.unique()):
    dd = [d for d in days if d[:7] == m]; a = np.array([A2[d] for d in dd]); c = np.array([CN[d] for d in dd])
    res["(1) by month"][m] = {"days": len(dd), "arm2": ci(a), "clean_nosite": ci(c), "arm2 - clean": ci(a - c)}
t = np.arange(len(days)); y = np.array([A2[d][0] for d in days]); yc = np.array([CN[d][0] for d in days])
def slope(y):
    b = np.polyfit(t, y, 1)[0] * 30; bs = []
    for _ in range(2000):
        ix = rng.integers(0, len(t), len(t)); bs.append(np.polyfit(t[ix], y[ix], 1)[0] * 30)
    return [round(float(b), 2), round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2)]
res["(1) trend: top-3 points per 30 days (OLS on daily hits)"] = {"arm2": slope(y), "clean_nosite": slope(yc), "arm2 - clean": slope(y - yc)}
# (2) covariates
cov = []
for d in days:
    g = X[X.day == d]; t3 = g.nsmallest(3, "rank"); v = g.votes
    cov.append({"day": d, "launches": len(g), "fth_top3": float(t3.fth.fillna(False).astype(float).mean()), "selfhunt_top3": float(t3.selfhunt.fillna(False).astype(float).mean()),
                "h25_top3": float(t3.h25.fillna(False).astype(float).mean()), "hunter_record_cov": float((g.hist_hunter_n > 0).mean()),
                "no1_vote_share": float(g.loc[g["rank"].idxmin(), "votes"] / v.sum()) if v.sum() > 0 else np.nan, "ai_share": float(g.topic_is_ai.mean()),
                "video_first": float(g.vidfirst.mean()) if g.vidfirst.notna().any() else np.nan, "hits3": A2[d][0]})
C = pd.DataFrame(cov); C["mon"] = C.day.str[:7]; FE = ["launches", "fth_top3", "selfhunt_top3", "h25_top3", "hunter_record_cov", "no1_vote_share", "ai_share", "video_first"]
res["(2) monthly means"] = C.groupby("mon")[FE + ["hits3"]].mean().round(3).to_dict(orient="index")
Cc = C.dropna(subset=FE).copy(); Z = (Cc[FE] - Cc[FE].mean()) / Cc[FE].std(); Z = np.column_stack([np.ones(len(Z)), Z.values]); yy = Cc.hits3.values
b = np.linalg.lstsq(Z, yy, rcond=None)[0]; bs = []
for _ in range(2000):
    ix = rng.integers(0, len(yy), len(yy)); bs.append(np.linalg.lstsq(Z[ix], yy[ix], rcond=None)[0])
bs = np.array(bs); res["(2) OLS daily arm-2 top-3 hits on standardized covariates (points per 1 SD)"] = {"n days": len(yy), **{f: [round(float(b[j + 1]), 2), round(float(np.percentile(bs[:, j + 1], 2.5)), 2), round(float(np.percentile(bs[:, j + 1], 97.5)), 2)] for j, f in enumerate(FE)}}
late = Cc[Cc.day >= "2026-09-01"]; early = Cc[Cc.day < "2026-09-01"]
res["(2) Sep-Oct minus Apr-Aug: covariate change x OLS coefficient = implied top-3 change"] = {f: round(float((late[f].mean() - early[f].mean()) / Cc[f].std() * b[j + 1]), 2) for j, f in enumerate(FE)}
res["(2) actual Sep-Oct minus Apr-Aug top-3"] = round(float(late.hits3.mean() - early.hits3.mean()), 2)
# (3) recency proxy
X["lv"] = np.log1p(X.votes.fillna(0)); X["y"] = X.lv - X.groupby("day").lv.transform("mean")
P3 = {}
for wgt in (1, 2, 3):
    pr = pd.Series(np.nan, index=X.index)
    for m in ("2026-09", "2026-10"):
        tr = X[X.mon < m]; te = X[X.mon == m]; cut = (pd.Timestamp(m + "-01") - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
        w = np.where(tr.day >= cut, wgt, 1.0); ps = []
        for s in range(3):
            mdl = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=s, verbose=-1)
            ps.append(mdl.fit(tr[INP], tr.y, sample_weight=w).predict(te[INP]))
        pr.loc[te.index] = np.mean(ps, 0)
    X[f"p_w{wgt}"] = pr; P3[wgt] = np.array([dm(X[X.day == d], f"p_w{wgt}") for d in days if d >= "2026-09-01"])
A2so = np.array([A2[d] for d in days if d >= "2026-09-01"])
res["(3) recency proxy, Sep-Oct (61 days)"] = {"arm2 (reference)": A2so.mean(0).round(1).tolist(), **{f"proxy w x{w}": P3[w].mean(0).round(1).tolist() for w in (1, 2, 3)},
                                              "x2 - x1": ci(P3[2] - P3[1]), "x3 - x1": ci(P3[3] - P3[1])}
# (4) live
rk = {d: dict(zip(g.id, g.daily_rank)) for d, g in L[L.daily_rank.notna()].groupby("day")}; lv = []
for f in sorted(glob.glob(f"{SP}/f05/*.json")):
    J = json.load(open(f)); d = J["day"]; F = pd.DataFrame(J.get("forecast") or [])
    if F.empty or d not in rk: continue
    F["id"] = F.id.astype(str); F = F[F.id.isin(rk[d])]; o = F.sort_values("predicted_rank").id.tolist(); t_ = sorted(rk[d], key=lambda i: rk[d][i])
    lv.append([len(set(o[:k]) & set(t_[:k])) / k * 100 for k in (3, 5, 10)])
res["(4) live published 00:05 (clean_nosite line), Nov days scored"] = {"days": len(lv), "top3/5/10": ci(np.array(lv)) if lv else None}
json.dump(res, open(os.path.join(OUT, "drift_0005.json"), "w"), indent=1, default=float)
for k, v in res.items():
    if k != "design": print(k, json.dumps(v, default=float)[:1500])
