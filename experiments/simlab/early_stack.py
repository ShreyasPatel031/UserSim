"""Early-hours model on the stack prior (orchestrator 08:34Z Nov 12). Same data, cuts, features and month-forward ridge as
early_model.py (E = current honest early model: clean LM + identity-free comments + pool + thread-position maker). Adds the
stack's thread inputs as of 00:05 PT (PH agent thread_feats / orchestrator stack, deployable version = clean_thread_z: clean LM
+ th_has_first, th_hunter_first, th_n_pre, th_fa_n, th_fa_rel; productLinks / media are not known at 00:05 live and are left out):
  STACK0  ridge (alpha 10) on within-day z of [honest] + TH, target within-day z of -log(rank), month-forward (the 00:05 stack line)
  E       early model ALL (unchanged)
  S       E + within-day z of [honest] + TH (the stack inputs; one stage, so no nested OOF needed)
  S_LMCOM LM + COM + TH (stack prior + comments only)
EZ / SZ  the same feature sets fit the stack's way (within-day z of every feature, target z of -log rank, alpha 10).
Per T: paired day bootstrap S - E, S - STACK0, E - STACK0; cap guard on days with <= 1 capped launch.
Identity: thread-position only (first top-level author, hunter from launches.poster), hashed ids in memory, nothing written.
    python early_stack.py <cf dir> <launches dir> <early dir (salt)> <v3 dir> <honest_preds_v2.parquet> <out dir>
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



# ---- stack thread features as of 00:05 PT (start + 4 min); hunter = launches.poster (hashed), never the API makers list
t5 = {li: L.start.iat[li] + pd.Timedelta(minutes=4) for li in range(len(L))}
fa5, npre = {}, {}
for li in range(len(L)):
    c = [v for v in com.get(li, {}).values() if v[1] <= t5[li]]
    tops = sorted([(v[1], v[0]) for v in c if v[2]]); fa5[li] = tops[0][1] if tops else None
    npre[li] = len({v[0] for v in c if v[0] != L.hunter.iat[li]})
L["rp"] = L.groupby("day")["rank"].rank(pct=True, ascending=False)
ev = {}
for li in range(len(L)):
    for u in {fa5[li], L.hunter.iat[li]} - {None}: ev.setdefault(u, set()).add((L.day.iat[li], L.rp.iat[li]))
th = []
for li, d in zip(B.li, B.day):
    fa, h = fa5[li], L.hunter.iat[li]; prev = [r for (dd, r) in ev.get(fa, ()) if dd < d] if fa else []
    th.append({"th_has_first": float(fa is not None), "th_hunter_first": float(fa is not None and fa == h), "th_n_pre": float(npre[li]),
               "th_fa_n": np.log1p(len(prev)), "th_fa_rel": (sum(prev) + 1.0) / (len(prev) + 2) if prev else 0.5})
B = pd.concat([B.reset_index(drop=True), pd.DataFrame(th)], axis=1)
TH = ["th_has_first", "th_hunter_first", "th_n_pre", "th_fa_n", "th_fa_rel"]
zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
B["zy"] = B.groupby("day")["rank"].transform(lambda r: zf(-np.log(r)))
ZT = []
for c in ["honest"] + TH: B["z_" + c] = B.groupby("day")[c].transform(zf); ZT.append("z_" + c)
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



mons = sorted(B.mon.unique())
def fit_stack(X):
    p = pd.Series(np.nan, index=X.index)
    for m in mons[1:]:
        tr, te = X[X.mon < m], X[X.mon == m]; p[te.index] = Ridge(alpha=10.0).fit(tr[ZT], tr.zy).predict(te[ZT])
    return p
capped_days = B.groupby("day").capped.sum(); low_cap = set(capped_days[capped_days <= 1].index)
res = {"design": __doc__.split("\n    python")[0], "launches": int(len(B)), "days": int(B.day.nunique()), "days_le1_capped": len(low_cap),
       "th_means_by_rank": B.assign(g=np.where(B["rank"] == 1, "1", np.where(B["rank"] <= 3, "2-3", np.where(B["rank"] <= 10, "4-10", "11+")))).groupby("g")[TH].mean().round(3).to_dict(), "by_T": {}}
X0 = B.copy(); X0["s"] = fit_stack(X0); P_st = per_day(X0, "s"); P_lm = per_day(X0.assign(s=X0.honest.where(X0.mon > mons[0])), "s")
j = P_st.index.intersection(P_lm.index); res["STACK0"] = dboot(P_st.loc[j]); res["clean LM alone"] = dboot(P_lm.loc[j]); res["STACK0 - clean LM (paired)"] = dboot(P_st.loc[j] - P_lm.loc[j], cols=("top3", "top5", "top10", "p1", "win"))
print("STACK0", res["STACK0"]["top3"], "LM", res["clean LM alone"]["top3"], "d", res["STACK0 - clean LM (paired)"]["top3"], flush=True)
ALLc = LMB + COM + POOL + MAKER
for tk, T in TS.items():
    X = pd.concat([B[["id", "day", "mon", "y", "rank", "capped"] + LMB + MAKER + ZT].reset_index(drop=True), feats_at(T)], axis=1)
    sets = {"E": ALLc, "S": ALLc + ZT, "S_LMCOM": LMB + COM + ZT, "LM+COM": LMB + COM}
    P = {k: per_day(X.assign(s=fit(X, c, "ridge")), "s") for k, c in sets.items()}; P["STACK0"] = P_st
    # stack method throughout: within-day z of every feature, target within-day z of -log(rank), alpha 10
    X["zy"] = B.zy.values
    for c in ALLc:
        if c not in ("honest",): X["zz_" + c] = X.groupby("day")[c].transform(zf)
    ZE = ["z_honest"] + ["zz_" + c for c in ALLc if c not in ("honest", "lm_rank", "lineup")]
    for nm, cols in (("EZ", ZE), ("SZ", ZE + [c for c in ZT if c != "z_honest"])):
        p = pd.Series(np.nan, index=X.index)
        for m in mons[1:]:
            tr, te = X[X.mon < m], X[X.mon == m]; p[te.index] = Ridge(alpha=10.0).fit(tr[cols].fillna(0), tr.zy).predict(te[cols].fillna(0))
        P[nm] = per_day(X.assign(s=p), "s")
    r = {k: dboot(v.loc[v.index.intersection(P["E"].index)]) for k, v in P.items()}
    for a, b in (("S", "E"), ("S", "STACK0"), ("E", "STACK0"), ("S_LMCOM", "LM+COM"), ("S_LMCOM", "STACK0"), ("SZ", "EZ"), ("SZ", "STACK0"), ("EZ", "STACK0"), ("SZ", "E"), ("EZ", "E")):
        j = P[a].index.intersection(P[b].index); r[f"{a} - {b} (paired)"] = dboot(P[a].loc[j] - P[b].loc[j], cols=("top3", "top5", "top10", "p1", "win"))
    for a, b in (("S", "E"), ("S", "STACK0")):
        j = sorted(set(P[a].index) & set(P[b].index) & low_cap); r[f"{a} - {b} on days with <= 1 capped launch"] = dboot(P[a].loc[j] - P[b].loc[j], cols=("top3", "top5", "p1"))
    res["by_T"][tk] = r
    print(tk, {k: r[k]["top3"] for k in ("STACK0", "E", "S", "S_LMCOM", "EZ", "SZ")}, "S-E", r["S - E (paired)"]["top3"], "SZ-STACK0", r["SZ - STACK0 (paired)"]["top3"], "SZ-E", r["SZ - E (paired)"]["top3"], flush=True)
json.dump(res, open(os.path.join(OUT, "early_stack.json"), "w"), indent=1, default=str)
# shadow candidate (not a replacement): SZ at +1h fit on all months, stack method (within-day z of every feature, alpha 10)
X = pd.concat([B[["id", "day", "mon", "y", "rank", "capped"] + LMB + MAKER + ZT].reset_index(drop=True), feats_at(TS["1h"])], axis=1)
X["zy"] = B.zy.values
for c in ALLc:
    if c != "honest": X["zz_" + c] = X.groupby("day")[c].transform(zf)
cols = ["z_honest"] + ["zz_" + c for c in ALLc if c not in ("honest", "lm_rank", "lineup")] + [c for c in ZT if c != "z_honest"]
m = Ridge(alpha=10.0).fit(X[cols].fillna(0), X.zy)
json.dump({"version": "early-stack-1h-v1 (shadow candidate)", "cut": "+1h after the 00:01 PT start (comments created <= 01:01 PT)",
           "score": "sum(coef[f] * z_f); z_f = within-day z over the line-up (0 if std 0, ddof 1); rank by score desc",
           "features": {"z_honest": "clean LM (clean_v3) score", "zz_c_*/zz_pool_n": "early_model.py comment / pool features at the cut",
                        "zz_<maker>": "early_model.py thread-position maker features", "z_th_*": "stack thread features as of 00:05 PT (thread_feats definitions)"},
           "coef": dict(zip(cols, map(float, m.coef_))), "fill_medians_maker": MED,
           "backtest": res["by_T"]["1h"]["SZ - E (paired)"] | {"vs": "current early model E at +1h"},
           "backtest_vs_stack0": res["by_T"]["1h"]["SZ - STACK0 (paired)"]}, open(os.path.join(OUT, "early_model_recipe_v2_stack_1h.json"), "w"), indent=1)
