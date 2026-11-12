"""One honest early-hours model (orchestrator 09:20Z Nov 12). At each cut T in {00:05, +1h, +2h, +3h, +4h} after the 00:01 PT start,
features known at T for every launch of the day, over the clean launch model (honest_preds_v2 = PH agent's clean_v3):
  LM       clean LM score (honest), its within-day rank, ln line-up size
  COM      identity-free comment features from the thread dumps (comments created <= T; team defined ONLY by thread position:
           the first top-level comment's author + the hunter): ln(1+) total non-team comments, top-level, replies, unique
           authors, comments in the last hour, share of the day's non-team comments, minutes to the first non-team comment (T if none)
  POOL     ln(1+) unique non-team commenters (<= T) who are complete-pool people (store_v3)
  MAKER    thread-position maker features: hunter is the first commenter (self-hunted), the first commenter's earlier launches
           (as first commenter or hunter, strictly earlier days; count, best rank, top-3 share, mean ln votes)
No feature uses the API makers list. Target ln(1+votes); ridge (alpha 3) and LightGBM, month-forward (each month scored by a model
fit on earlier months). Per day: top 3/5/10, #1/#2/#3 pick in top 3, exact winner; paired by day vs LM-only, 2,000 day bootstraps.
Ablation: LM + each block, all, all minus each block. Cap guard: the dumps hold at most 20 top-level threads per launch; results
also on days with <= 1 capped launch. Calibration of the combined ridge per T: P(final top 3) for picks 1-5. Recipe JSON (features,
standardisation, ridge weights per T, fit on all months) for the live early P points.
    python early_model.py <cf dir> <launches dir> <early dir (salt)> <v3 dir> <honest_preds_v2.parquet> <out dir>
"""
import glob, gzip, hashlib, json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
import lightgbm as lgb

CFD, LDIR, EDIR, V3, HP, OUT = sys.argv[1:7]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
SALT = open(os.path.join(EDIR, "salt")).read().strip()
pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna()].copy(); L["id"] = L.id.astype(str); L["y"] = np.log1p(pd.to_numeric(L.votes).astype(float)); L["rank"] = L.daily_rank.astype(float)
L = L.sort_values(["day", "id"]).reset_index(drop=True); bys = {s: i for i, s in enumerate(L.slug)}
L["start"] = pd.to_datetime(L.day).dt.tz_localize("UTC") + pd.to_timedelta(np.where(L.day < "2026-11-01", 7, 8), "h") + pd.Timedelta(minutes=1)
L["hunter"] = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in L.poster]
com, ntop = {}, {}
for f in sorted(glob.glob(os.path.join(CFD, "page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        i = bys[p_["slug"]]; out = com.setdefault(i, {}); edges = (p_.get("threads") or {}).get("edges") or []; ntop[i] = max(ntop.get(i, 0), len(edges))
        def walk(n, top):
            u = ((n.get("user") or {}).get("username") or "").lower(); t = n.get("createdAt")
            if u and t: out[n.get("id")] = (pid(u), pd.Timestamp(t).tz_convert("UTC"), top)
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"], False)
        for e in edges: walk(e["node"], True)
CAP = max(ntop.values()); L["capped"] = [float(ntop.get(i, 0) >= CAP) for i in range(len(L))]
comp = set(pd.read_parquet(os.path.join(V3, "persons.parquet")).query("complete").person_id)
H = pd.read_parquet(HP)[["id", "honest"]]; H["id"] = H.id.astype(str)
days = set(pd.read_parquet(os.path.join(CFD, "cf_rows.parquet")).day.unique())
first_author = {}
for i, c in com.items():
    tops = sorted([(v[1], v[0]) for v in c.values() if v[2]]); first_author[i] = tops[0][1] if tops else None
# history of first commenters / hunters (earlier launches, thread-position identity only)
hist = {}
for i in range(len(L)):
    for p in {first_author.get(i), L.hunter.iat[i]} - {None}: hist.setdefault(p, []).append((L.day.iat[i], L.y.iat[i], L["rank"].iat[i], i))
TS = {"0005": pd.Timedelta(minutes=4), "1h": pd.Timedelta(hours=1), "2h": pd.Timedelta(hours=2), "3h": pd.Timedelta(hours=3), "4h": pd.Timedelta(hours=4)}
B = L[L.day.isin(days)].merge(H, on="id", how="inner"); idx = [int(np.flatnonzero(L.id.values == i)[0]) for i in B.id] if False else None
pos = {i: k for k, i in enumerate(L.id)}; B["li"] = B.id.map(pos)
B["lineup"] = np.log(B.groupby("day").id.transform("size")); B["lm_rank"] = B.groupby("day").honest.rank(ascending=False); B["mon"] = B.day.str[:7]
mk = []
for li, d in zip(B.li, B.day):
    fa, h = first_author.get(li), L.hunter.iat[li]
    v = [x for x in hist.get(fa, []) if x[0] < d] if fa and fa != h else []
    ks, ys = np.array([a[2] for a in v]), np.array([a[1] for a in v])
    mk.append({"self_hunted_thread": float(fa is not None and fa == h), "no_first": float(fa is None), "fa_prior": np.log1p(len(v)), "fa_best": np.log1p(ks.min()) if len(v) else np.nan,
               "fa_top3": (ks <= 3).mean() if len(v) else np.nan, "fa_ymean": ys.mean() if len(v) else np.nan})
B = pd.concat([B.reset_index(drop=True), pd.DataFrame(mk)], axis=1)
MED = {}
for c in ("fa_best", "fa_top3", "fa_ymean"):
    B[c + "_na"] = B[c].isna().astype(float); MED[c] = float(B[c].median()); B[c] = B[c].fillna(MED[c])
MAKER = ["self_hunted_thread", "no_first", "fa_prior", "fa_best", "fa_top3", "fa_ymean", "fa_best_na"]
LMB = ["honest", "lm_rank", "lineup"]; COM = ["c_tot", "c_top", "c_rep", "c_auth", "c_last1h", "c_share", "c_first_min"]; POOL = ["pool_n"]


def feats_at(T):
    rows = []
    for li in B.li:
        st = L.start.iat[li]; lim = st + T; team = {first_author.get(li), L.hunter.iat[li]} - {None}
        c = [v for v in com.get(li, {}).values() if v[1] <= lim and v[0] not in team]
        ts = [v[1] for v in c]; au = {v[0] for v in c}
        rows.append({"c_tot": np.log1p(len(c)), "c_top": np.log1p(sum(v[2] for v in c)), "c_rep": np.log1p(sum(not v[2] for v in c)), "c_auth": np.log1p(len(au)),
                     "c_last1h": np.log1p(sum(t > lim - pd.Timedelta(hours=1) for t in ts)), "_n": len(c),
                     "c_first_min": (min(ts) - st).total_seconds() / 60 if ts else T.total_seconds() / 60, "pool_n": np.log1p(len(au & comp))})
    F = pd.DataFrame(rows); F["day"] = B.day.values
    F["c_share"] = F._n / F.groupby("day")._n.transform("sum").replace(0, np.nan); F["c_share"] = F.c_share.fillna(0)
    return F[COM + POOL]


mons = sorted(B.mon.unique())


def fit(X, cols, kind):
    p = pd.Series(np.nan, index=X.index)
    for m in mons[1:]:
        tr, te = X[X.mon < m], X[X.mon == m]
        if kind == "ridge":
            mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9; p[te.index] = Ridge(alpha=3.0).fit((tr[cols] - mu) / sd, tr.y).predict((te[cols] - mu) / sd)
        else:
            g = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=40, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
            p[te.index] = g.fit(tr[cols], tr.y).predict(te[cols])
    return p


def per_day(X, col, sub=None):
    out = {}
    for d, g in X[X[col].notna()].groupby("day"):
        if sub is not None and d not in sub: continue
        if len(g) < 8 or (g["rank"] <= 3).sum() < 3: continue
        o = g.assign(_j=rng.random(len(g)) * 1e-9).sort_values([col, "_j"], ascending=False)
        out[d] = [len(set(o.id[:k]) & set(g.id[g["rank"] <= k])) / k * 100 for k in (3, 5, 10)] + [float(o["rank"].iat[j] <= 3) * 100 for j in range(5)] + [float(o["rank"].iat[0] == 1) * 100]
    return pd.DataFrame(out, index=["top3", "top5", "top10", "p1", "p2", "p3", "p4", "p5", "win"]).T


def dboot(X, B_=2000, cols=("top3", "top5", "top10", "p1", "p2", "p3", "win")):
    X = X[list(cols)]; v = X.values; bs = np.array([v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(B_)])
    return {c: [round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j, c in enumerate(cols)} | {"days": int(len(v))}


capped_days = B.groupby("day").capped.sum(); low_cap = set(capped_days[capped_days <= 1].index)
res = {"design": __doc__.split("\n    python")[0], "launches": int(len(B)), "days": int(B.day.nunique()), "thread_cap": int(CAP),
       "share_launches_capped_by_rank": B.assign(g=np.where(B["rank"] == 1, "1", np.where(B["rank"] <= 3, "2-3", np.where(B["rank"] <= 10, "4-10", "11+")))).groupby("g").capped.mean().round(3).to_dict(),
       "days_with_le1_capped": len(low_cap), "by_T": {}}
recipe = {"version": "early-v1", "target": "ln(1+final votes)", "lm": "honest_preds_v2 (clean_v3) score", "team_rule": "first top-level comment author + hunter",
          "features": LMB + COM + POOL + MAKER, "fill_medians": MED, "per_T": {}}
recipe_com = {"version": "early-v1-com", "target": "ln(1+final votes)", "lm": "honest_preds_v2 (clean_v3) score", "team_rule": "first top-level comment author + hunter",
              "features": LMB + COM, "per_T": {}}
for tk, T in TS.items():
    X = pd.concat([B[["id", "day", "mon", "y", "rank", "capped"] + LMB + MAKER].reset_index(drop=True), feats_at(T)], axis=1)
    sets = {"LM": LMB, "LM+COM": LMB + COM, "LM+POOL": LMB + POOL, "LM+MAKER": LMB + MAKER, "ALL": LMB + COM + POOL + MAKER,
            "ALL-COM": LMB + POOL + MAKER, "ALL-POOL": LMB + COM + MAKER, "ALL-MAKER": LMB + COM + POOL}
    P = {k: per_day(X.assign(s=fit(X, c, "ridge")), "s") for k, c in sets.items()}
    X["s_gbm"] = fit(X, LMB + COM + POOL + MAKER, "gbm"); P["ALL (LightGBM)"] = per_day(X, "s_gbm")
    base = P["LM"]; r = {}
    for k, Pk in P.items():
        j = base.index.intersection(Pk.index); r[k] = dboot(Pk.loc[j])
        if k != "LM": r[k + " - LM (paired)"] = dboot(Pk.loc[j] - base.loc[j], cols=("top3", "top5", "p1", "win"))
    for a, b in (("ALL", "ALL-COM"), ("ALL", "ALL-POOL"), ("ALL", "ALL-MAKER")):
        j = P[a].index.intersection(P[b].index); r[f"{a} - {b} (paired) = what {b[4:]} adds"] = dboot(P[a].loc[j] - P[b].loc[j], cols=("top3", "top5", "p1", "win"))
    Xs = X.assign(s=fit(X, sets["ALL"], "ridge")); Ploc = per_day(Xs, "s", low_cap); Bloc = per_day(X.assign(s=fit(X, LMB, "ridge")), "s", low_cap); j = Ploc.index.intersection(Bloc.index)
    r["ALL on days with <= 1 capped launch"] = dboot(Ploc.loc[j]); r["ALL - LM on those days (paired)"] = dboot(Ploc.loc[j] - Bloc.loc[j], cols=("top3", "top5", "p1", "win"))
    PA = P["ALL"]; r["calibration ALL ridge: P(top 3) for picks 1-5"] = {f"#{k}": [round(float(PA[f'p{k}'].mean()), 1), int(len(PA))] for k in range(1, 6)}
    res["by_T"][tk] = r
    cm = sets["LM+COM"]; mu2, sd2 = X[cm].mean(), X[cm].std() + 1e-9; m2 = Ridge(alpha=3.0).fit((X[cm] - mu2) / sd2, X.y); PC = P["LM+COM"]
    recipe_com["per_T"][tk] = {"mean": {c: float(mu2[c]) for c in cm}, "sd": {c: float(sd2[c]) for c in cm}, "coef": dict(zip(cm, map(float, m2.coef_))), "intercept": float(m2.intercept_),
                               "calibration_p_top3_picks_1_5": [round(float(PC[f'p{k}'].mean()) / 100, 3) for k in range(1, 6)]}
    cols = sets["ALL"]; mu, sd = X[cols].mean(), X[cols].std() + 1e-9; m = Ridge(alpha=3.0).fit((X[cols] - mu) / sd, X.y)
    recipe["per_T"][tk] = {"mean": {c: float(mu[c]) for c in cols}, "sd": {c: float(sd[c]) for c in cols}, "coef": dict(zip(cols, map(float, m.coef_))), "intercept": float(m.intercept_),
                           "calibration_p_top3_picks_1_5": [round(float(PA[f'p{k}'].mean()) / 100, 3) for k in range(1, 6)]}
    print(tk, "LM", r["LM"]["top3"], "ALL", r["ALL"]["top3"], "d", r["ALL - LM (paired)"]["top3"], "gbm", r["ALL (LightGBM)"]["top3"], flush=True)
recipe["notes"] = ("cut T after 00:01 PT; comments created <= T; non-team = not the first top-level author and not the hunter; c_* are ln(1+count) "
                   "except c_share (share of the day's non-team comments at T) and c_first_min (minutes, T if none); pool_n needs the complete-pool id list; "
                   "fa_* = the first commenter's earlier launches (as first commenter or hunter); NaN fa_* -> training medians (mean values here are post-fill)")
json.dump(res, open(os.path.join(OUT, "early_model.json"), "w"), indent=1, default=str)
json.dump(recipe, open(os.path.join(OUT, "early_model_recipe_v1.json"), "w"), indent=1)
recipe_com["notes"] = recipe["notes"]; json.dump(recipe_com, open(os.path.join(OUT, "early_model_recipe_v1_lm_com.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k not in ("design", "by_T")}, default=str))
