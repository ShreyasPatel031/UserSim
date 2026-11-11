"""Simulation conditioned on the first hours (orchestrator Nov 11, 20:45Z): who showed up early -> launch shock and who next.
E_T(L) = complete pool people (store_v3) with an exact-timed comment on L between launch start (00:01 PT) and +T h,
T in {1, 2, 4}; the launch's own team (real maker/poster handles; "[REDACTED]" placeholders dropped) is excluded.
Exact comment times: people_live profile crawl (slug-keyed, mapped to launch id) + PH API v2 live/backfill.

Launch level. Target = per-launch multiplier r = logv - base, where base is the it8 LM's out-of-sample log-vote prediction
(lm_breakout_e5_fix preds, monthly folds). Features of E_T, all dated strictly before L's start (upvotes by launch day <= d-2):
  A count     log1p |E_T|
  B identity  A + one-off vs regular accounts, activity tiers (prior upvotes / prior comments), prior early-commenting habit,
              prior ties to the team (upvoted/commented any earlier launch of a team member), overlap with voters of top-3 launches
              of the previous 30 days, and base itself
  C +follow   B + follow-graph features from the Nov follow snapshot (not dated; leak risk, reported separately)
Month-forward: LightGBM trained on launches of months < m, scored on month m (m = Apr..Nov). Metrics: within-day Spearman of
predicted vs true r; daily top 3/5/10 overlap with the real daily ranking of base + predicted r, paired by day vs base (LM only).

Person level (rows: tl_cp_all19 line-ups, 19 days Oct 20 - Nov 8). For people not in E_T(L): co-upvote affinity between the person
and E_T members (cosine of SVD user factors of the upvote matrix fitted on upvotes dated <= fold cutoff, the cold_start folds),
max and sum over E_T; plus |E_T|. Logistic fitted on Oct days, scored on Nov days and vice versa. Hit@1/Hit@3/AUC within each
person-day line-up vs the popularity baseline (base; activity is constant within a line-up).

    python early_engagers.py <workdir>   (workdir: v3/, launches/, preds.parquet, rows.parquet)
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy import sparse
from scipy.stats import spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
import lightgbm as lgb

W = sys.argv[1]; OUT = os.path.join(W, "out"); os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(0); TS = (1, 2, 4)


def _real(h):
    return bool(h) and not str(h).startswith("[") and str(h).strip().lower() not in ("redacted", "none", "null")


# ---------------- launches, team, LM preds
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(W, "launches", "*.parquet"))])
L = L.sort_values("updated_at").drop_duplicates("id", keep="last").reset_index(drop=True); L["id"] = L.id.astype(str)
SALT = open(os.path.join(W, "salt")).read().strip()
import hashlib
pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
team = {}
for i, mk, po in zip(L.id, L.makers, L.poster):
    ms = json.loads(mk) if isinstance(mk, str) and mk.startswith("[") else []
    team[i] = {pid(m) for m in ms if _real(m)} | ({pid(po)} if _real(po) else set())
P = pd.read_parquet(os.path.join(W, "preds.parquet"))[["id", "base", "day", "dailyRank", "logv"]]
P["id"] = P.id.astype(str); P["r"] = P.logv - P.base
P["start"] = pd.to_datetime(P.day).dt.tz_localize("UTC") + pd.to_timedelta(np.where(P.day < "2026-11-01", 7, 8), "h") + pd.Timedelta(minutes=1)
start = dict(zip(P.id, P.start)); pday = dict(zip(P.id, P.day))
print("preds", len(P), P.day.min(), P.day.max(), flush=True)

# ---------------- events
comp = set(pd.read_parquet(os.path.join(W, "v3", "persons.parquet")).query("complete").person_id)
ev = pd.read_parquet(os.path.join(W, "v3", "events.parquet"), columns=["person_id", "kind", "target_id", "ts_lo", "ts_quality", "extra"])
ev = ev[ev.person_id.isin(comp)]
s2id = dict(zip("launch:" + L.slug, L.id)); Lday = dict(zip(L.id, L.day))
C = ev[(ev.kind == "comment") & (ev.ts_quality == "exact")][["person_id", "target_id", "ts_lo"]].copy()
C["lid"] = C.target_id.map(s2id).fillna(C.target_id)
C = C[C.lid.isin(set(L.id))].drop_duplicates(["person_id", "lid", "ts_lo"])
C["lstart"] = C.lid.map(lambda x: pd.Timestamp(Lday[x], tz="UTC") + pd.Timedelta(hours=7 if Lday[x] < "2026-11-01" else 8, minutes=1))
C["h"] = (C.ts_lo - C.lstart).dt.total_seconds() / 3600
C = C[C.h >= -0.05]                                      # a comment before launch start = slug mismatch
first = C.groupby(["lid", "person_id"]).agg(h=("h", "min"), ts=("ts_lo", "min")).reset_index()
first = first[[p not in team.get(l, set()) for l, p in zip(first.lid, first.person_id)]]
print("exact comments on launches", len(C), "first-comment pairs (non-team)", len(first), flush=True)

U = ev[ev.kind == "upvote"][["person_id", "target_id", "ts_lo", "extra"]].copy(); U["target_id"] = U.target_id.astype(str)
U["vday"] = U.target_id.map(Lday)
U["vday"] = U.vday.fillna(U.extra.str.extract(r'"launched_at": "(\d{4}-\d\d-\d\d)')[0])
U = U.dropna(subset=["vday"])[["person_id", "target_id", "vday"]].drop_duplicates(); del ev
print("dated upvotes", len(U), flush=True)
rank = dict(zip(L.id, L.daily_rank))

# ---------------- E_T pairs and identity features (all dated before the launch)
pairs = []
for T in TS:
    e = first[(first.h <= T) & first.lid.isin(set(P.id))][["lid", "person_id", "h"]].copy(); e["T"] = T; pairs.append(e)
E = pd.concat(pairs, ignore_index=True); E["d"] = E.lid.map(pday)
E["d2"] = (pd.to_datetime(E.d) - pd.Timedelta(days=2)).dt.strftime("%Y-%m-%d")
E["d32"] = (pd.to_datetime(E.d) - pd.Timedelta(days=32)).dt.strftime("%Y-%m-%d")
E["lstart"] = E.lid.map(start)
ep = set(E.person_id)
Ue = U[U.person_id.isin(ep)].copy(); Ue["top3"] = Ue.target_id.map(rank).le(3)
Ce = first[first.person_id.isin(ep)][["person_id", "lid", "h", "ts"]]
uniq = E[["person_id", "lid", "d2", "d32", "lstart"]].drop_duplicates()
m = uniq.merge(Ue, on="person_id")
m = m[m.vday <= m.d2]
f_up = m.groupby(["person_id", "lid"]).agg(n_up=("target_id", "size"), n_top3=("top3", lambda s: 0)).reset_index()
mt = m[m.top3 & (m.vday >= m.d32)].groupby(["person_id", "lid"]).size().rename("n_top3_30d")
mm = m[["person_id", "lid", "target_id"]]
mm = mm[[bool(team.get(t, set()) & team.get(l, set())) for t, l in zip(mm.target_id, mm.lid)]]
tie_up = mm.groupby(["person_id", "lid"]).size().rename("tie_up")
m2 = uniq.merge(Ce.rename(columns={"lid": "olid"}), on="person_id"); m2 = m2[m2.ts < m2.lstart]
f_c = m2.groupby(["person_id", "lid"]).agg(n_com=("olid", "size"), n_early=("h", lambda s: int((s <= 1).sum()))).reset_index()
m2 = m2[[bool(team.get(o, set()) & team.get(l, set())) for o, l in zip(m2.olid, m2.lid)]]
tie_c = m2.groupby(["person_id", "lid"]).size().rename("tie_com")
F = uniq[["person_id", "lid"]].merge(f_up.drop(columns="n_top3"), how="left", on=["person_id", "lid"]).merge(f_c, how="left", on=["person_id", "lid"])
for s in (mt, tie_up, tie_c): F = F.merge(s.reset_index(), how="left", on=["person_id", "lid"])
F = F.fillna(0)
fo = pd.read_parquet(os.path.join(W, "v3", "events.parquet"), columns=["person_id", "kind", "target_id"]).query("kind == 'follows'")[["person_id", "target_id"]]
indeg = fo.groupby("target_id").size()
F["n_followers_pool"] = F.person_id.map(indeg).fillna(0)
fset = set(zip(fo.person_id, fo.target_id)); del fo
F["follow_tie"] = [int(any((p, t) in fset or (t, p) in fset for t in team.get(l, ()))) for p, l in zip(F.person_id, F.lid)]
E = E.merge(F, on=["person_id", "lid"], how="left")
E["oneoff"] = ((E.n_up < 5) & (E.n_com == 0)).astype(int); E["regular"] = (E.n_up >= 50).astype(int)
E["tie"] = ((E.tie_up + E.tie_com) > 0).astype(int)
print("E_T rows", len(E), flush=True)

agg = E.groupby(["lid", "T"]).agg(n=("person_id", "size"), n_oneoff=("oneoff", "sum"), n_regular=("regular", "sum"),
    lup_mean=("n_up", lambda s: np.log1p(s).mean()), lcom_mean=("n_com", lambda s: np.log1p(s).mean()),
    n_earlyhabit=("n_early", lambda s: int((s >= 3).sum())), early_sum=("n_early", lambda s: np.log1p(s).sum()),
    n_tie=("tie", "sum"), n_top3v=("n_top3_30d", lambda s: int((s > 0).sum())), top3_sum=("n_top3_30d", lambda s: np.log1p(s).sum()),
    n_fol_tie=("follow_tie", "sum"), fol_sum=("n_followers_pool", lambda s: np.log1p(s).sum()), fol_max=("n_followers_pool", "max"),
    h_mean=("h", "mean")).reset_index()

A_COLS = ["ln"]
B_COLS = A_COLS + ["n_oneoff", "n_regular", "lup_mean", "lcom_mean", "n_earlyhabit", "early_sum", "n_tie", "n_top3v", "top3_sum", "h_mean", "base", "base_dz"]
C_COLS = B_COLS + ["n_fol_tie", "fol_sum", "fol_max"]


def boot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4), int(len(v))]


def topk_hits(D, score):
    out = {k: [] for k in (3, 5, 10)}; days = []
    for d, g in D.groupby("day"):
        days.append(d)
        for k in (3, 5, 10):
            out[k].append(len(set(g.nlargest(k, score).id) & set(g.nsmallest(k, "dailyRank").id)) / k * 100)
    return days, {k: np.array(v) for k, v in out.items()}


res = {"design": __doc__.split("\n    python")[0], "coverage": {}, "launch_level": {}}
months = sorted(P.day.str[:7].unique())
for T in TS:
    D = P.merge(agg[agg["T"] == T].drop(columns="T"), left_on="id", right_on="lid", how="left")
    D[[c for c in agg.columns if c not in ("lid", "T")]] = D[[c for c in agg.columns if c not in ("lid", "T")]].fillna(0)
    D["ln"] = np.log1p(D.n); D["base_dz"] = D.base - D.groupby("day").base.transform("mean")
    res["coverage"][f"T{T}"] = {"share_launches_with_E_T": round(float((D.n > 0).mean()), 3), "mean_E_T": round(float(D.n.mean()), 2),
                               "mean_E_T_if_any": round(float(D.n[D.n > 0].mean()), 2)}
    for vname, cols in (("A_count", A_COLS), ("B_identity", B_COLS), ("C_identity_follow", C_COLS)):
        D["pred"] = np.nan
        for mo in months[1:]:
            tr, te = D.day.str[:7] < mo, D.day.str[:7] == mo
            mdl = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=40, subsample=0.8,
                                    subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, random_state=0)
            mdl.fit(D.loc[tr, cols], D.loc[tr, "r"]); D.loc[te, "pred"] = mdl.predict(D.loc[te, cols])
        T_ = D[D.pred.notna()].copy(); T_["score"] = T_.base + T_.pred
        sp = T_.groupby("day").apply(lambda g: spearmanr(g.pred, g.r)[0] if g.pred.std() > 0 else np.nan)
        days, hv = topk_hits(T_, "score"); _, hb = topk_hits(T_, "base")
        late = np.array([d >= "2026-10-20" for d in days])
        r = {"within_day_spearman_pred_vs_true_r": boot(sp.values),
             "within_day_spearman_Oct20_Nov8": boot(sp[sp.index >= "2026-10-20"].values)}
        for k in (3, 5, 10):
            r[f"top{k}"] = boot(hv[k]); r[f"top{k} minus LM-only (paired by day)"] = boot(hv[k] - hb[k])
            r[f"top{k} minus LM-only, Oct20-Nov8"] = boot(hv[k][late] - hb[k][late])
        r["per_month_spearman"] = {mo: round(float(sp[sp.index.str[:7] == mo].mean()), 3) for mo in months[1:]}
        res["launch_level"][f"T{T} {vname}"] = r
        print(T, vname, r["within_day_spearman_pred_vs_true_r"], r["top3 minus LM-only (paired by day)"], flush=True)
    if T == 1:
        _, hb = topk_hits(T_, "base"); res["launch_level"]["LM-only"] = {f"top{k}": boot(hb[k]) for k in (3, 5, 10)}
json.dump(res, open(os.path.join(OUT, "early_engagers.json"), "w"), indent=1)

# ---------------- person level
R = pd.read_parquet(os.path.join(W, "rows.parquet")); R["launch_id"] = R.launch_id.astype(str)
R = R.merge(P[["id", "base"]].rename(columns={"id": "launch_id"}), on="launch_id", how="inner")
FOLDS = [("oct", "2026-10-18", "2026-10-20", "2026-10-31"), ("nov", "2026-10-30", "2026-11-01", "2026-11-30")]
pres = {}
for T in TS:
    ET = E[E["T"] == T].groupby("lid").person_id.apply(list).to_dict()
    X = R.copy(); X["inET"] = [p in set(ET.get(l, ())) for p, l in zip(X.person_id, X.launch_id)]
    X = X[~X.inET].copy(); X["nET"] = X.launch_id.map(lambda l: len(ET.get(l, ()))); X["aff_max"] = 0.0; X["aff_sum"] = 0.0
    for name, cut, te0, te1 in FOLDS:
        Uf = U[U.vday <= cut]; users = {p: i for i, p in enumerate(Uf.person_id.unique())}; items = {t: i for i, t in enumerate(Uf.target_id.unique())}
        M = sparse.csr_matrix((np.ones(len(Uf)), (Uf.person_id.map(users), Uf.target_id.map(items))), shape=(len(users), len(items)))
        M = M.multiply(1 / np.sqrt(np.asarray(M.sum(0)).ravel() + 1)).tocsr()
        Z = TruncatedSVD(64, random_state=0).fit_transform(M); Z /= np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9
        sub = X[(X.d >= te0) & (X.d <= te1)]
        for l, g in sub.groupby("launch_id"):
            em = [users[p] for p in ET.get(l, ()) if p in users]
            if not em: continue
            pi = np.array([users.get(p, -1) for p in g.person_id]); ok = pi >= 0
            S = Z[pi[ok]] @ Z[np.array(em)].T
            X.loc[g.index[ok], "aff_max"] = S.max(1); X.loc[g.index[ok], "aff_sum"] = S.clip(0).sum(1)
    X["zb"] = X.groupby(["d", "person_id"]).base.transform(lambda s: (s - s.mean()) / (s.std() + 1e-9))
    X["lnET"] = np.log1p(X.nET); nov = X.d >= "2026-11-01"
    for vn, cols in (("count", ["zb", "lnET"]), ("count_affinity", ["zb", "lnET", "aff_max", "aff_sum"])):
        X[vn] = np.nan
        for trm, tem in ((~nov, nov), (nov, ~nov)):
            lr = LogisticRegression(C=1.0, max_iter=500).fit(X.loc[trm, cols], X.loc[trm, "y"]); X.loc[tem, vn] = lr.decision_function(X.loc[tem, cols])
    X["popularity"] = X.zb; X["rand"] = rng.random(len(X))

    def per_day(s):
        g = X.groupby(["d", "person_id"]); pos = g.y.transform("sum"); n = g.y.transform("size")
        A = X[pos > 0].copy(); A["rk"] = A.groupby(["d", "person_id"])[s].rank(ascending=False, method="first")
        h1 = A[A.rk <= 1].groupby(["d", "person_id"]).y.max().groupby(level=0).mean()
        h3 = A[A.rk <= 3].groupby(["d", "person_id"]).y.max().groupby(level=0).mean()
        Bq = X[(pos > 0) & (pos < n)]
        au = Bq.groupby(["d", "person_id"]).apply(lambda q: roc_auc_score(q.y, q[s])).groupby(level=0).mean()
        return pd.DataFrame({"Hit@1": h1, "Hit@3": h3, "AUC": au})
    base_ = per_day("popularity"); out = {"popularity (base)": {k: boot(v) for k, v in base_.items()},
                                          "rows": int(len(X)), "share_rows_launch_has_E_T": round(float((X.nET > 0).mean()), 3)}
    for vn in ("count", "count_affinity"):
        pdd = per_day(vn); out[vn] = {k: boot(v) for k, v in pdd.items()} | {f"{k} minus popularity (paired by day)": boot(pdd[k] - base_[k]) for k in pdd}
    pres[f"T{T}"] = out; print("person", T, json.dumps(out)[:600], flush=True)
res["person_level"] = pres
json.dump(res, open(os.path.join(OUT, "early_engagers.json"), "w"), indent=1)
print("done", flush=True)
