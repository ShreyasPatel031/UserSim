"""Young / created-together commenters as forecast features (orchestrator 12:29Z Nov 13). Counts only.
Cuts T (PT, launch day): pre = 00:05, 00:30, 01:00, 02:00. Commenters = non-team authors (team = hunter + listed makers) of comments with
createdAt <= T in the launch thread dumps. Age = launch-day 00:00 PT - about.joined (exact, people_live/vm files). Features per cut:
  y30 / y90 / y365 = share of commenters with joined aged < 30 / 90 / 365 d; band = share aged 30-365 d;
  cl50 / cl500 = share of commenters (with ph_user_id) within 50 / 500 ids of another commenter on the launch, minus the mean of
  20 same-size random draws from that month's commenter ids.
Fewer than 3 commenters with joined (ids for cl*): feature = day mean (within-day z = 0) and flag few = 1 enters every arm.
Base: clean (honest_preds_v2) + th_n_pre (distinct non-hunter commenters by 00:05) at pre; + nc = ln(1+ all comments <= T) at later cuts.
Month-forward ridge (alpha 10) on within-day z, target z(-ln rank); days with thread data and >= 10 launches. Top 3/5/10 overlap with the
real top-k, paired by day vs base, 2,000 day bootstraps; partial r of each feature with the target beyond the base (day bootstrap).
(3) Explanatory: per launch (Oct 1 - Nov 10, >= 20 store upvoters), discount = ln(displayed / store upvoters) vs the band share and the
cluster excess of its listed UPVOTERS; 5-fold CV by launch, ridge, base = ln(store upvoters) + rank band. MSE gain, launch bootstrap.
(4) Live readiness, Nov 10-13: share of non-team commenters by 00:30 / 01:00 PT (live comments_ts) that were complete in the store version
live at the launch start (store_v3 _prev_20261110T0910Z for Nov 10, _prev_20261113T1148Z for Nov 11-13) with a join date before the day.
    python young_comm.py <scratchpad> <store dir> <out dir>
"""
import glob, gzip, hashlib, json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
SP, ST, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); PT = "America/Los_Angeles"; res = {}
SALT = open(f"{SP}/early/salt").read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
J = pd.read_parquet(f"{SP}/acct/joined.parquet").drop_duplicates("person_id"); J["jt"] = pd.to_datetime(J.joined, utc=True, errors="coerce"); J["uid"] = pd.to_numeric(J.ph_user_id, errors="coerce")
jt = J.dropna(subset=["jt"]).set_index("person_id").jt; uidm = J.dropna(subset=["uid"]).set_index("person_id").uid
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()].reset_index(drop=True)
def mk(m):
    try: return [pid(x) for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
L["h"] = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in L.poster]; L["team"] = [set(mk(m)) | ({h} if h else set()) for m, h in zip(L.makers, L.h)]
L["d0"] = [pd.Timestamp(d).tz_localize(PT, ambiguous=True).tz_convert("UTC") for d in L.day]
bys = {s: i for i, s in enumerate(L.slug)}; com = {}
for f in sorted(glob.glob(f"{SP}/cf/page*.jsonl.gz")):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        out = com.setdefault(bys[p_["slug"]], {})
        def walk(n):
            u = ((n.get("user") or {}).get("username") or "").lower(); t = n.get("createdAt")
            if u and t: out[n.get("id")] = (pid(u), pd.Timestamp(t).tz_convert("UTC"))
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
CUTS = {"pre": 5, "0030": 30, "0100": 60, "0200": 120}
def near(u, d):
    u = np.sort(u); g = np.diff(u); n = np.zeros(len(u), bool); n[1:] |= g <= d; n[:-1] |= g <= d; return n.mean()
rows = []
for i, c in com.items():
    r = L.iloc[i]; base = {"id": r.id, "i": i}
    pre_users = {p for p, t in c.values() if t <= r.d0 + pd.Timedelta(minutes=5) and p != r.h}; base["th_n_pre"] = len(pre_users)
    for cn, mins in CUTS.items():
        lim = r.d0 + pd.Timedelta(minutes=mins); ppl = {p for p, t in c.values() if t <= lim and p not in r.team}
        base[f"nc_{cn}"] = sum(1 for p, t in c.values() if t <= lim); ag = np.array([(r.d0 - jt[p]).total_seconds() / 86400 for p in ppl if p in jt.index])
        base[f"n_{cn}"] = len(ppl); base[f"nj_{cn}"] = len(ag)
        for t in (30, 90, 365): base[f"y{t}_{cn}"] = float((ag < t).mean()) if len(ag) >= 3 else np.nan
        base[f"band_{cn}"] = float(((ag >= 30) & (ag < 365)).mean()) if len(ag) >= 3 else np.nan
        base[f"uids_{cn}"] = [uidm[p] for p in ppl if p in uidm.index]
    rows.append(base)
X = pd.DataFrame(rows).merge(L[["id", "day", "daily_rank"]], on="id"); H = pd.read_parquet(f"{SP}/honest_preds_v2.parquet")[["id", "honest"]]; H["id"] = H.id.astype(str); X = X.merge(H, on="id")
X["mon"] = X.day.str[:7]
for cn in CUTS:
    pool = {m: np.unique(np.concatenate([np.array(u) for u in g[f"uids_{cn}"] if len(u)] or [np.array([])])) for m, g in X.groupby("mon")}
    for d in (50, 500):
        v = []
        for u, m in zip(X[f"uids_{cn}"], X.mon):
            if len(u) < 3 or len(pool[m]) < len(u): v.append(np.nan); continue
            v.append(near(np.array(u), d) - np.mean([near(rng.choice(pool[m], len(u), replace=False), d) for _ in range(20)]))
        X[f"cl{d}_{cn}"] = v
X = X[X.groupby("day").id.transform("count") >= 10].copy(); X["rank"] = X.daily_rank.astype(float)
z = lambda s: (s - s.mean()) / (s.std() or 1)
X["y"] = X.groupby("day")["rank"].transform(lambda r: z(-np.log(r)))
FE = ["y30", "y90", "y365", "band", "cl50", "cl500"]
for c in ["honest", "th_n_pre"] + [f"nc_{cn}" for cn in CUTS] + [f"{f}_{cn}" for f in FE for cn in CUTS]:
    s = X[c] if c == "honest" or c.split("_")[0] in FE else np.log1p(X[c]); X["z_" + c] = s.groupby(X.day).transform(z).fillna(0)
for cn in CUTS: X[f"few_{cn}"] = (X[f"nj_{cn}"] < 3).astype(float)
mons = sorted(X.mon.unique())
def ov(g, col): o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def resid(v, Z): Z1 = np.c_[np.ones(len(v)), Z]; return v - Z1 @ np.linalg.lstsq(Z1, v, rcond=None)[0]
days = X.day.unique(); res["data"] = {"launches": len(X), "days": len(days), "months": [mons[0], mons[-1]]}
for cn in CUTS:
    B0 = ["z_honest", "z_th_n_pre"] + ([f"z_nc_{cn}"] if cn != "pre" else []) + [f"few_{cn}"]
    arms = {"base": B0, **{f"+{f}": B0 + [f"z_{f}_{cn}"] for f in FE}, "+all": B0 + [f"z_{f}_{cn}" for f in FE]}
    for a, cols in arms.items():
        X[a] = np.nan
        for m in mons[1:]:
            tr, te = X[X.mon < m], X[X.mon == m]; X.loc[te.index, a] = Ridge(alpha=10).fit(tr[cols], tr.y).predict(te[cols])
    T = X[X["base"].notna()]; o = {"coverage: commenters with joined / all": [int(T[f"nj_{cn}"].sum()), int(T[f"n_{cn}"].sum())],
        "launches with >=3 commenters with joined": [int((T[f"nj_{cn}"] >= 3).sum()), len(T)], "scored days": int(T.day.nunique()),
        "levels top3/5/10": {a: np.array([ov(g, a) for _, g in T.groupby("day")]).mean(0).round(1).tolist() for a in arms}}
    for a in arms:
        if a == "base": continue
        d = np.array([np.array(ov(g, a)) - np.array(ov(g, "base")) for _, g in T.groupby("day")]); bs = np.array([d[rng.integers(0, len(d), len(d))].mean(0) for _ in range(2000)])
        o[f"{a} - base top3/5/10 [CI]"] = [[round(float(d[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
    Tq = T[T[f"nj_{cn}"] >= 3]; dq = Tq.day.unique()
    for f in FE:
        col = f"{f}_{cn}"; Q = Tq[Tq[col].notna()]
        def pr(D): return np.corrcoef(resid(D.y.values, D[B0].values), resid(D[col].values, D[B0].values))[0, 1]
        bsv = [pr(pd.concat([Q[Q.day == x] for x in rng.choice(dq, len(dq))])) for _ in range(500)]
        o[f"partial r {f} (launches with >=3)"] = [round(float(pr(Q)), 4), round(float(np.nanpercentile(bsv, 2.5)), 4), round(float(np.nanpercentile(bsv, 97.5)), 4), len(Q)]
    res[f"cut {cn}"] = o; print(cn, json.dumps(o), flush=True)
# (3) explanatory: listed upvoters vs discount
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse  # noqa: E402
WL = warehouse.table("launches", do_sync=False); WL["id"] = WL.id.astype(str); WL = WL.sort_values("updated_at").drop_duplicates("id", keep="last")
W = WL[WL.daily_rank.notna() & (WL.day >= "2026-10-01") & (WL.day <= "2026-11-10")].copy(); W["votes"] = pd.to_numeric(W.votes, errors="coerce").astype(float)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"].drop_duplicates(["person_id", "target_id"]).copy(); U["target_id"] = U.target_id.astype(str); U = U[U.target_id.isin(set(W.id))]
W = W.set_index("id"); W["su"] = U.groupby("target_id").size().reindex(W.index).fillna(0); W = W[(W.su >= 20) & (W.votes > 0)].copy(); W["mon"] = W.day.str[:7]
W["d0"] = [pd.Timestamp(d).tz_localize(PT).tz_convert("UTC") for d in W.day]; U = U[U.target_id.isin(W.index)]
U["age"] = (U.target_id.map(W.d0) - U.person_id.map(jt)).dt.total_seconds() / 86400; U["uid"] = U.person_id.map(uidm)
W["band"] = U.groupby("target_id").age.apply(lambda a: ((a >= 30) & (a < 365)).sum() / a.notna().sum() if a.notna().sum() else np.nan)
pm = {m: U[U.target_id.map(W.mon) == m].uid.dropna().unique() for m in W.mon.unique()}
W["clus"] = [near(g.values, 50) - np.mean([near(rng.choice(pm[W.at[t, "mon"]], len(g), replace=False), 50) for _ in range(10)]) if len(g) >= 3 else np.nan for t, g in ((t, U[U.target_id == t].uid.dropna()) for t in W.index)]
W = W.dropna(subset=["band", "clus"]); W["disc"] = np.log(W.votes / W.su); W["lsu"] = np.log(W.su); W["r3"] = (W.daily_rank <= 3).astype(float); W["r10"] = (W.daily_rank <= 10).astype(float)
fo = rng.integers(0, 5, len(W)); A3 = {"base": ["lsu", "r3", "r10"], "+band": ["lsu", "r3", "r10", "band"], "+cluster": ["lsu", "r3", "r10", "clus"], "+both": ["lsu", "r3", "r10", "band", "clus"]}; pr_ = {}
for a, cols in A3.items():
    p = np.zeros(len(W))
    for k in range(5): tr = fo != k; p[~tr] = Ridge(alpha=1).fit(W[cols][tr], W.disc[tr]).predict(W[cols][~tr])
    pr_[a] = (p - W.disc.values) ** 2
o = {"launches": len(W), "CV R2": {a: round(float(1 - v.mean() / W.disc.var()), 4) for a, v in pr_.items()}}
for a in ("+band", "+cluster", "+both"):
    d = pr_["base"] - pr_[a]; b = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]; o[f"MSE gain {a} [CI]"] = [round(float(d.mean()), 5), round(float(np.percentile(b, 2.5)), 5), round(float(np.percentile(b, 97.5)), 5)]
res["(3) listed upvoters -> discount ln(displayed/store)"] = o; print(json.dumps(o), flush=True)
# (4) live readiness
pv = {"2026-11-10": f"{SP}/acct/prev/_prev_20261110T0910Z.parquet"}; o4 = {}
for d in ("2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"):
    PP = pd.read_parquet(pv.get(d, f"{SP}/acct/prev/_prev_20261113T1148Z.parquet")); comp = set(PP[PP.complete].person_id); d0 = pd.Timestamp(d).tz_localize(PT).tz_convert("UTC")
    os.system(f"gsutil -q cp gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_at_launch/{d}/live/comments_ts.jsonl {SP}/acct/cts_{d}.jsonl")
    C = pd.read_json(f"{SP}/acct/cts_{d}.jsonl", lines=True); C = C[~C.is_maker.fillna(False).astype(bool) & ~C.is_hunter.fillna(False).astype(bool)]
    C["t"] = pd.to_datetime(C.created_at, utc=True, errors="coerce"); C["p"] = [pid(u) for u in C.username.fillna("")]
    for cn, mins in (("0030", 30), ("0100", 60)):
        S = C[C.t <= d0 + pd.Timedelta(minutes=mins)].drop_duplicates(["launch_id", "p"]); ok = S.p.isin(comp) & S.p.map(jt).lt(d0).fillna(False)
        g = S.assign(ok=ok).groupby("launch_id").ok.agg(["sum", "size"])
        o4[f"{d} by {cn}"] = {"commenter-launch pairs": len(S), "in live store with join date": int(ok.sum()), "share": round(float(ok.mean()), 3) if len(S) else None,
                              "launches with >=3 covered / with any commenter": [int((g["sum"] >= 3).sum()), len(g)]}
res["(4) live readiness"] = o4; print(json.dumps(o4))
json.dump(res, open(f"{OUT}/result.json", "w"), indent=1, default=float)
