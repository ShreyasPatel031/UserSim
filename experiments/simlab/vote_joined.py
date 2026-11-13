"""Account age from the exact join date (about.joined + ph_user_id in raw/ph_population/people_live/vm/<handle>.json; orchestrator 12:11Z Nov 13).
joined.parquet = (salted person_id, joined, ph_user_id) read from every per-person file (handles never kept). Counts only.
(a) Coverage over store / complete persons; ph_user_id -> joined monotonicity (isotonic CV error), checking the earlier id-curve route.
(b) Account age at vote = launch day 00:01 PT - joined (store upvote rows carry no vote time). Share of a launch's listed upvoters (with joined)
    under 7/30/90/365 days, over-covered vs matched (vote_newacct.py matching), top-3 separately; launch bootstrap.
(c) Weights: displayed ~ store upvoters by age cell (<30d, 30-365d, >365d, no joined), bounded [0,1], near-complete launches
    (store >= 0.9 x displayed), 5-fold CV by launch vs one shared weight.
(d) Near-consecutive ph_user_id among a launch's upvoters (within 50 / 500 ids), excess over same-size draws from that month.
(e) Early: store upvotes have no vote time, so EARLY = non-team commenters in the first 4 h (thread dumps; team = first top-level author
    + hunter). Share of young accounts (<30/<90/<365 d) among early commenters with joined; does it predict ln(1+final votes) and top-3
    beyond the clean LM (honest_preds_v2)? OLS coefficient and partial correlation, day-cluster bootstrap; launches with >=3 such commenters.
    python vote_joined.py <store dir> <joined.parquet> <cf dir> <launches dir> <salt dir> <honest_preds_v2.parquet> <out dir>
"""
import glob, gzip, hashlib, json, os, sys
import numpy as np, pandas as pd
from sklearn.isotonic import IsotonicRegression
from scipy.optimize import lsq_linear
ST, JP, CFD, LDIR, SD, HP, OUT = sys.argv[1:8]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); res = {}
SALT = open(os.path.join(SD, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
tod = lambda s: pd.to_datetime(s, utc=True, errors="coerce").dt.tz_localize(None).values.astype("datetime64[s]").astype("float") / 86400
J = pd.read_parquet(JP).drop_duplicates("person_id"); J["jd"] = tod(J.joined); J["uid"] = pd.to_numeric(J.ph_user_id, errors="coerce")
P = pd.read_parquet(os.path.join(ST, "persons.parquet")); C = set(P[P.complete].person_id); Jk = J[J.jd.notna()]; jd = Jk.set_index("person_id").jd; uid = J.dropna(subset=["uid"]).set_index("person_id").uid
r = Jk.dropna(subset=["uid"]).sort_values("uid"); x = r.uid.values; y = r.jd.values; f = rng.integers(0, 5, len(r)); e = np.zeros(len(r))
for k in range(5): e[f == k] = IsotonicRegression(out_of_bounds="clip").fit(x[f != k], y[f != k]).predict(x[f == k]) - y[f == k]
res["(a) coverage"] = {"files read": len(J), "with joined": len(Jk), "with ph_user_id": int(J.uid.notna().sum()),
    "store persons with joined": [len(set(jd.index) & set(P.person_id)), len(P)], "complete persons with joined": [len(set(jd.index) & C), len(C)],
    "id->joined isotonic CV abs err days (median, p90, p99)": [round(float(np.median(np.abs(e))), 3), round(float(np.percentile(np.abs(e), 90)), 2), round(float(np.percentile(np.abs(e), 99)), 1)]}
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse  # noqa: E402
WL = warehouse.table("launches", do_sync=False); WL["id"] = WL.id.astype(str); WL = WL.sort_values("updated_at").drop_duplicates("id", keep="last")
W = WL[WL.daily_rank.notna() & (WL.day >= "2026-10-01") & (WL.day <= "2026-11-10")].copy(); W["votes"] = pd.to_numeric(W.votes, errors="coerce").astype(float); W["rank"] = W.daily_rank.astype(float)
E = pd.read_parquet(os.path.join(ST, "events.parquet"), columns=["person_id", "kind", "target_id"]); L = E[E.kind == "upvote"].drop_duplicates(["person_id", "target_id"]).copy()
L["target_id"] = L.target_id.astype(str); L = L[L.target_id.isin(set(W.id))]
W = W.set_index("id"); W["store_up"] = L.groupby("target_id").size().reindex(W.index).fillna(0); W = W[W.store_up > 0]
W["over"] = W.store_up > W.votes; W["mon"] = W.day.str[:7]; W["rb"] = pd.cut(W["rank"], [0, 3, 10, 1000], labels=["1-3", "4-10", "11+"]).astype(str)
W["d0"] = tod(pd.Series(W.day.values)) + 8 / 24
L["age"] = L.target_id.map(W.d0) - L.person_id.map(jd); L["uid"] = L.person_id.map(uid)
ov_up = L[L.target_id.isin(W[W.over].index)]
res["(a) coverage"]["upvoter rows with joined: 62 over-covered / all Oct1-Nov10"] = [[int(ov_up.age.notna().sum()), len(ov_up)], [int(L.age.notna().sum()), len(L)]]
res["(a) coverage"]["upvoter rows with age < 0 (joined after launch day start; same-day signups)"] = int((L.age < 0).sum())
K = L[L.age.notna()].copy()
for t in (7, 30, 90, 365): K[f"u{t}"] = K.age < t
def near(u, d):
    u = np.sort(u); g = np.diff(u); n = np.zeros(len(u), bool); n[1:] |= g <= d; n[:-1] |= g <= d; return n.mean() if len(u) else np.nan
S = K.groupby("target_id")[["u7", "u30", "u90", "u365"]].mean(); S["n_j"] = K.groupby("target_id").size()
Ku = L[L.uid.notna()]; pool_m = {m: Ku[Ku.target_id.map(W.mon) == m].uid.unique() for m in W.mon.unique()}
for d in (50, 500):
    ob = Ku.groupby("target_id").uid.apply(lambda s: near(s.values, d))
    ex = {t: ob[t] - np.mean([near(rng.choice(pool_m[W.at[t, "mon"]], len(g), replace=False), d) for _ in range(20)]) for t, g in Ku.groupby("target_id").uid}
    S[f"near{d}"] = ob; S[f"near{d}_excess"] = pd.Series(ex)
W = W.join(S); Wt = W[W.n_j >= 5]; ov = Wt[Wt.over]; nov = Wt[~Wt.over]; pairs = []
for i, rr in ov.iterrows():
    pool = nov[(nov.mon == rr.mon) & (nov.rb == rr.rb) & nov.votes.between(0.7 * rr.votes, 1.3 * rr.votes)]
    if len(pool): pairs.append((i, list(pool.index)))
def boot(d):
    d = d[~np.isnan(d)]; b = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]; return [round(float(d.mean()), 4), round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]
res["(b/d) launches"] = {"with >=5 upvoters with joined": len(Wt), "over-covered among them": len(ov), "with matched pool": len(pairs)}
for k in ("u7", "u30", "u90", "u365", "near50", "near500", "near50_excess", "near500_excess"):
    av = np.array([Wt.at[i, k] for i, _ in pairs], float); bv = np.array([np.nanmean(Wt.loc[p, k].values.astype(float)) for _, p in pairs]); d = av - bv
    t3 = [j for j, (i, _) in enumerate(pairs) if Wt.at[i, "rb"] == "1-3"]
    res[k] = {"over mean": round(float(np.nanmean(av)), 4), "matched mean": round(float(np.nanmean(bv)), 4), "diff [95% CI]": boot(d), f"top-3 diff (n={len(t3)})": boot(d[t3])}
# (c) weights
L["cell"] = pd.cut(L.age, [-1e9, 30, 365, 1e9], labels=["<30d", "30-365d", ">365d"]).astype(str).replace("nan", "no joined")
N = L.groupby(["target_id", "cell"]).size().unstack(fill_value=0).reindex(W.index).fillna(0); nc = (W.store_up >= 0.9 * W.votes).values; N = N[nc]; W2 = W[nc]; cols = list(N.columns)
X = N.values.astype(float); yv = W2.votes.values; fo = rng.integers(0, 5, len(W2)); pa = np.zeros(len(W2)); pb = np.zeros(len(W2)); wts = []
for k in range(5):
    tr = fo != k; s = lsq_linear(X[tr], yv[tr], bounds=(0, 1)); wts.append(s.x); pa[~tr] = X[~tr] @ s.x
    pb[~tr] = X[~tr].sum(1) * lsq_linear(X[tr].sum(1, keepdims=True), yv[tr], bounds=(0, 1)).x[0]
d = np.abs(pb - yv) - np.abs(pa - yv); bb = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
res["(c) weights by age cell"] = {"n near-complete launches": len(W2), "cell totals": dict(zip(cols, [int(v) for v in X.sum(0)])),
    "weights fold mean [min, max]": {c: [round(float(np.mean([w[j] for w in wts])), 3), round(float(min(w[j] for w in wts)), 3), round(float(max(w[j] for w in wts)), 3)] for j, c in enumerate(cols)},
    "OOF MAE cells / single": [round(float(np.abs(pa - yv).mean()), 2), round(float(np.abs(pb - yv).mean()), 2)], "MAE gain [95% CI]": [round(float(d.mean()), 2), round(float(np.percentile(bb, 2.5)), 2), round(float(np.percentile(bb, 97.5)), 2)]}
# (e) early commenters
A = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
A = A[A.daily_rank.notna() & A.votes.notna()].copy(); A["id"] = A.id.astype(str); A["y"] = np.log1p(pd.to_numeric(A.votes).astype(float)); A["rank"] = A.daily_rank.astype(float)
A = A.reset_index(drop=True); bys = {s: i for i, s in enumerate(A.slug)}
A["start"] = pd.to_datetime(A.day).dt.tz_localize("UTC") + pd.to_timedelta(np.where(A.day < "2026-11-01", 7, 8), "h") + pd.Timedelta(minutes=1)
A["hunter"] = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in A.poster]
com = {}
for fn in sorted(glob.glob(os.path.join(CFD, "page*.jsonl.gz"))):
    for line in gzip.open(fn):
        xx = json.loads(line)
        try: p_ = json.loads(xx["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        out = com.setdefault(bys[p_["slug"]], {})
        def walk(n, top):
            u = ((n.get("user") or {}).get("username") or "").lower(); t = n.get("createdAt")
            if u and t: out[n.get("id")] = (pid(u), pd.Timestamp(t).tz_convert("UTC"), top)
            for e_ in ((n.get("replies") or {}).get("edges") or []): walk(e_["node"], False)
        for e_ in ((p_.get("threads") or {}).get("edges") or []): walk(e_["node"], True)
H = pd.read_parquet(HP)[["id", "honest"]]; H["id"] = H.id.astype(str); A = A.merge(H, on="id", how="inner")
rows = []
for i, rr in A.iterrows():
    c = com.get(bys.get(rr.slug)) if rr.slug in bys else None
    if not c: continue
    tops = sorted([(v[1], v[0]) for v in c.values() if v[2]]); team = {tops[0][1] if tops else None, rr.hunter} - {None}
    st = rr.start; d0 = st.tz_localize(None).to_datetime64().astype("datetime64[s]").astype(float) / 86400
    ppl = {v[0] for v in c.values() if v[1] <= st + pd.Timedelta(hours=4) and v[0] not in team}
    ag = np.array([d0 - jd[p] for p in ppl if p in jd.index])
    rows.append((rr.id, rr.day, rr.y, rr["rank"], rr.honest, len(ppl), len(ag), *(float((ag < t).mean()) if len(ag) else np.nan for t in (30, 90, 365))))
R = pd.DataFrame(rows, columns=["id", "day", "y", "rank", "honest", "n_early", "n_joined", "y30", "y90", "y365"])
R["top3"] = (R["rank"] <= 3).astype(float); R["lnn"] = np.log1p(R.n_early); Rq = R[R.n_joined >= 3].copy()
res["(e) early commenters"] = {"launches with thread dumps + clean pred": len(R), "with >=3 early non-team commenters with joined": len(Rq), "days": int(Rq.day.nunique()),
    "early commenters with joined / all": [int(R.n_joined.sum()), int(R.n_early.sum())], "mean young share <30/<90/<365": [round(float(Rq[c].mean()), 4) for c in ("y30", "y90", "y365")]}
def resid(v, Z): Z1 = np.c_[np.ones(len(v)), Z]; return v - Z1 @ np.linalg.lstsq(Z1, v, rcond=None)[0]
days = Rq.day.unique()
for c in ("y30", "y90", "y365"):
    for tgt in ("y", "top3"):
        def stat(D):
            Z = D[["honest", "lnn"]].values; a = resid(D[tgt].values, Z); b = resid(D[c].values, Z)
            return np.corrcoef(a, b)[0, 1], (a @ b) / (b @ b)
        pc, beta = stat(Rq); bs = []
        for _ in range(1000):
            dd = rng.choice(days, len(days)); bs.append(stat(pd.concat([Rq[Rq.day == x] for x in dd]))[0])
        res["(e) early commenters"][f"{c} -> {tgt} | clean LM + ln(1+n early)"] = {"partial r": round(float(pc), 4), "95% CI (day bootstrap)": [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)], "slope": round(float(beta), 4)}
json.dump(res, open(os.path.join(OUT, "result.json"), "w"), indent=1); print(json.dumps(res, indent=1))
