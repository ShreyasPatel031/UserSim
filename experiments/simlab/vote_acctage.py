"""Account age of upvoters on over-covered launches (orchestrator 12:06Z Nov 13). Counts only.
(1) PH numeric user id -> createdAt: isotonic fit on hunters+makers from day files (2025 history + 2026 daily), 5-fold CV error.
(2) Coverage: store persons for which we hold the numeric id (user_id_map + day-file user objects, matched by salted handle hash).
(3) Account age at vote = launch day - fitted createdAt(id). Share of upvoters (with id) under 30/90/365 days, over-covered vs matched
    (vote_newacct.py matching: same month and rank band, votes +/-30%), launch bootstrap. Weights: displayed votes ~ counts of store
    upvoters by age cell (+ "no id" cell), bounded LS in [0,1] on near-complete launches (store >= 0.9 x displayed), 5-fold CV by launch vs a single shared weight.
(4) Near-consecutive ids (also excess over a same-size random draw of id-known upvoters from that month): share of a launch's id-known upvoters with another id-known upvoter of the same launch within 50 / 500 ids.
    python vote_acctage.py <store dir> <ref.parquet> <pid_uid.parquet> <out dir>
"""
import json, os, sys
import numpy as np, pandas as pd
from sklearn.isotonic import IsotonicRegression
from scipy.optimize import lsq_linear
ST, REF, PU, OUT = sys.argv[1:5]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); res = {}
R = pd.read_parquet(REF).sort_values("uid"); x = R.uid.values.astype(float); y = R.created.dt.tz_localize(None).values.astype("datetime64[s]").astype("int64") / 86400
f = rng.integers(0, 5, len(R)); err = np.zeros(len(R))
for k in range(5): err[f == k] = IsotonicRegression(out_of_bounds="clip").fit(x[f != k], y[f != k]).predict(x[f == k]) - y[f == k]
a = np.abs(err) * 24; recent = (R.created >= pd.Timestamp("2024-01-01", tz="UTC")).values
res["(1) id->createdAt fit"] = {"ref users": len(R), "CV median abs err hours": round(float(np.median(a)), 2), "p90 hours": round(float(np.percentile(a, 90)), 2),
                               "p99 hours": round(float(np.percentile(a, 99)), 1), "2024+ accounts n / median h": [int(recent.sum()), round(float(np.median(a[recent])), 2)],
                               "max ref id created": str(R.created.max())[:10]}
iso = IsotonicRegression(out_of_bounds="clip").fit(x, y)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse  # noqa: E402
WL = warehouse.table("launches", do_sync=False); WL["id"] = WL.id.astype(str); WL = WL.sort_values("updated_at").drop_duplicates("id", keep="last")
W = WL[WL.daily_rank.notna() & (WL.day >= "2026-10-01") & (WL.day <= "2026-11-10")].copy(); W["votes"] = pd.to_numeric(W.votes, errors="coerce").astype(float); W["rank"] = W.daily_rank.astype(float)
P = pd.read_parquet(os.path.join(ST, "persons.parquet")); C = set(P[P.complete].person_id)
E = pd.read_parquet(os.path.join(ST, "events.parquet"), columns=["person_id", "kind", "target_id"]); L = E[E.kind == "upvote"].drop_duplicates(["person_id", "target_id"]).copy()
L["target_id"] = L.target_id.astype(str); L = L[L.target_id.isin(set(W.id))]
M = pd.read_parquet(PU).set_index("pid").uid; L["uid"] = L.person_id.map(M)
W = W.set_index("id"); W["store_up"] = L.groupby("target_id").size().reindex(W.index).fillna(0); W = W[W.store_up > 0]
W["over"] = W.store_up > W.votes; W["mon"] = W.day.str[:7]; W["rb"] = pd.cut(W["rank"], [0, 3, 10, 1000], labels=["1-3", "4-10", "11+"]).astype(str)
ids = set(M.index) & set(P.person_id); ov_up = L[L.target_id.isin(W[W.over].index)]
res["(2) coverage of numeric ids"] = {"store persons": [len(ids), len(P)], "complete persons": [len(ids & C), len(C)],
    "upvoter rows on the 62 over-covered (with id / all)": [int(ov_up.uid.notna().sum()), len(ov_up)],
    "upvoter rows, all Oct1-Nov10 launches (with id / all)": [int(L.uid.notna().sum()), len(L)],
    "note": "id-known people come from maker/hunter/profile sources, so they skew towards makers"}
K = L[L.uid.notna()].copy(); K["lday"] = pd.to_datetime(K.target_id.map(W.day)).values.astype("datetime64[s]").astype("int64") / 86400
K["age"] = K.lday - iso.predict(K.uid.values.astype(float))
for t in (30, 90, 365): K[f"u{t}"] = K.age < t
def near(g, d):
    u = np.sort(g.uid.values); gap = np.diff(u); n = np.zeros(len(u), bool); n[1:] |= gap <= d; n[:-1] |= gap <= d; return n.mean()
S = K.groupby("target_id")[["u30", "u90", "u365"]].mean(); S["n_id"] = K.groupby("target_id").size()
pool_m = {m: K[K.target_id.map(W.mon) == m].uid.unique() for m in W.mon.unique()}
def exp_near(lid, n, d, reps=20):
    p = pool_m[W.at[lid, "mon"]]; return np.mean([near(pd.DataFrame({"uid": rng.choice(p, min(n, len(p)), replace=False)}), d) for _ in range(reps)])
for d in (50, 500):
    S[f"near{d}"] = K.groupby("target_id")[["uid"]].apply(lambda g: near(g, d))
    S[f"near{d}_excess"] = [S.at[t, f"near{d}"] - exp_near(t, int(S.at[t, "n_id"]), d) for t in S.index]
W = W.join(S); Wt = W[W.n_id >= 5]; ov = Wt[Wt.over]; nov = Wt[~Wt.over]; pairs = []
for i, r in ov.iterrows():
    pool = nov[(nov.mon == r.mon) & (nov.rb == r.rb) & nov.votes.between(0.7 * r.votes, 1.3 * r.votes)]
    if len(pool): pairs.append((i, list(pool.index)))
res["(3/4) launches"] = {"with >=5 id-known upvoters": len(Wt), "over-covered among them": len(ov), "with matched pool": len(pairs)}
def boot(d):
    b = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]; return [round(float(d.mean()), 4), round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]
for k in ("u30", "u90", "u365", "near50", "near500", "near50_excess", "near500_excess"):
    av = np.array([Wt.at[i, k] for i, _ in pairs]); bv = np.array([Wt.loc[p, k].mean() for _, p in pairs]); d = av - bv
    o = {"over mean": round(float(av.mean()), 4), "matched mean": round(float(bv.mean()), 4), "diff [95% CI]": boot(d)}
    t3 = [j for j, (i, _) in enumerate(pairs) if Wt.at[i, "rb"] == "1-3"]
    if len(t3) >= 3: o[f"top-3 diff (n={len(t3)})"] = boot(d[t3])
    res[k] = o
# (3b) weights by age cell
L["cell"] = "no id"; ag = K.set_index(["person_id", "target_id"]).age; idx = pd.MultiIndex.from_frame(L[["person_id", "target_id"]])
age = pd.Series(ag.reindex(idx).values, index=L.index)
L.loc[age.notna(), "cell"] = pd.cut(age[age.notna()], [-1e9, 30, 90, 365, 1e9], labels=["<30d", "30-90d", "90-365d", ">365d"]).astype(str)
N = L.groupby(["target_id", "cell"]).size().unstack(fill_value=0).reindex(W.index).fillna(0); cols = list(N.columns)
nc = (W.store_up >= 0.9 * W.votes).values; N = N[nc]; W2 = W[nc]
X = N.values.astype(float); yv = W2.votes.values; fo = rng.integers(0, 5, len(W2)); pa = np.zeros(len(W2)); pb = np.zeros(len(W2)); wts = []
for k in range(5):
    tr = fo != k; s = lsq_linear(X[tr], yv[tr], bounds=(0, 1)); wts.append(s.x); pa[~tr] = X[~tr] @ s.x
    s1 = lsq_linear(X[tr].sum(1, keepdims=True), yv[tr], bounds=(0, 1)); pb[~tr] = X[~tr].sum(1) * s1.x[0]
ea, eb = np.abs(pa - yv), np.abs(pb - yv); d = eb - ea; bb = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
res["(3b) weights (displayed ~ store upvoters by account-age cell, [0,1], 5-fold CV by launch)"] = {
    "cells": cols, "cell totals": [int(c) for c in X.sum(0)], "weights (fold mean, min-max)": {c: [round(float(np.mean([w[j] for w in wts])), 3), round(float(min(w[j] for w in wts)), 3), round(float(max(w[j] for w in wts)), 3)] for j, c in enumerate(cols)},
    "OOF MAE age cells / single weight": [round(float(ea.mean()), 2), round(float(eb.mean()), 2)], "MAE gain (single - cells) [95% CI]": [round(float(d.mean()), 2), round(float(np.percentile(bb, 2.5)), 2), round(float(np.percentile(bb, 97.5)), 2)], "n launches (near-complete: store upvoters >= 0.9 x displayed)": len(W2)}
json.dump(res, open(os.path.join(OUT, "result.json"), "w"), indent=1); print(json.dumps(res, indent=1))
