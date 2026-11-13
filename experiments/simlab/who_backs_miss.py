"""Miss anatomy of the who-backs-it FULL model (orchestrator 18:12Z Nov 13). Same setup as who_backs2.py (exec'd up to the arms; FULL =
all features, 30 training days). For each launch, held voters NOT in the top-N list (N = round expected backers) are bucketed, first
match wins: (A) dormant: no upvote on a launch dated in the 60 days before the day (incl. not in the scored population), with
account-age split from persons.joined; (B) active but zero tie: no backed-before / follow / is-hunter tie and zero topic taste;
(D) voted for >= 5 launches that day (votes on everything); (C) the rest: had a tie or taste signal but ranked below N (distance in
places). D is checked before C so C is "model under-ranked a person who is not a mass voter". Reverse: top-N people who did not vote for
the launch: activity (upvotes 30 d), share among the 1,000 most active, share who voted for another launch that day. Oracle: recall at N
if all missed backers of the buckets so far were hits (cumulative A, A+B, A+B+D, all). Launch-bootstrap intervals. Counts only.
    python who_backs_miss.py <store dir> <clean_live_rows_nosite.parquet> <launches dir> <salt dir> <out dir>
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); src = open(os.path.join(HERE, "who_backs2.py")).read(); exec(src[src.index("import os, sys, json, time"):src.index("ARMS = {")])
voters = U[U.lday.isin(DAYS)].groupby("target_id").person_id.agg(set).to_dict()
JT = pd.to_datetime(pd.read_parquet(os.path.join(V3, "persons.parquet")).set_index("person_id").joined, utc=True, errors="coerce")
nday = U[U.lday.isin(DAYS)].groupby(["person_id", "lday"]).size()
cols = COLS; rows = []; rev = []
for d in DAYS:
    tr = [t for t in sorted(TRAIN) if t < d][-30:]
    m = LogisticRegression(max_iter=400).fit(np.vstack([TRAIN[t][0] for t in tr]), np.concatenate([TRAIN[t][1] for t in tr]), sample_weight=np.where(np.concatenate([TRAIN[t][1] for t in tr]) == 1, 1.0, 10.0))
    act, out = TEST[d]; idx = {p: k for k, p in enumerate(act.index)}; lastd = act["last"].values; n30 = act.n30.values
    top1k = set(act.sort_values("n30", ascending=False).index[:1000]); d0 = pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC")
    lu = set(C[C.day == d].id); voted_any = set(U[U.lday == d].person_id)
    for i, Xi in out:
        if i not in lu: continue
        v = voters.get(i, set())
        if not v: continue
        p = m.predict_proba(Xi)[:, 1]; o = np.argsort(-p); rk = np.empty(len(p), int); rk[o] = np.arange(len(p)); N = max(1, int(round(p.sum()))); top = set(act.index[o[:N]])
        a = {"A": 0, "A_age<30": 0, "A_age30-365": 0, "A_age>365": 0, "B": 0, "D": 0, "C": 0}; dist = []
        for q in v - top:
            k = idx.get(q)
            if k is None or lastd[k] > 60:
                a["A"] += 1; ag = (d0 - JT.get(q)).days if q in JT.index and pd.notna(JT.get(q)) else None
                a["A_age<30" if ag is not None and ag < 30 else ("A_age30-365" if ag is not None and ag < 365 else "A_age>365")] += 1; continue
            x = Xi[k]
            if x[ci["back"]] == 0 and x[ci["fol"]] == 0 and x[ci["hun"]] == 0 and x[ci["taste"]] == 0: a["B"] += 1; continue
            if nday.get((q, d), 0) >= 5: a["D"] += 1; continue
            a["C"] += 1; dist.append(rk[k] - N + 1)
        rp = len(v & set(act.index[o[:len(v)]])) / len(v)
        rows.append({"id": i, "day": d, "n_voters": len(v), "hit": len(v & top), "N": N, "rprec": rp, **a, "c_dist_med": float(np.median(dist)) if dist else np.nan})
        nv = [q for q in top if q not in v]
        if nv: rev.append({"n30_nonvoters_med": float(np.median([n30[idx[q]] for q in nv])), "n30_voters_med": float(np.median([n30[idx[q]] for q in v if q in idx])) if any(q in idx for q in v) else np.nan,
                           "share_top1000": float(np.mean([q in top1k for q in nv])), "share_voted_other": float(np.mean([q in voted_any for q in nv])), "n": len(nv)})
R = pd.DataFrame(rows); RV = pd.DataFrame(rev)
def lb(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
miss = R.n_voters - R.hit; R = R[miss > 0].assign(miss=miss[miss > 0])
res = {"launches": len(R), "days": DAYS, "R-precision FULL (list size = real held-voter count)": lb(R.rprec), "recall@N": lb(R.hit / R.n_voters), "missed held backers total": int(R.miss.sum())}
res["bucket shares of missed backers (mean over launches)"] = {b: lb(R[b] / R.miss) for b in ("A", "B", "D", "C")}
res["A account-age split (share of A)"] = {k: round(float(R[k].sum() / max(R.A.sum(), 1)), 3) for k in ("A_age<30", "A_age30-365", "A_age>365")}
res["C distance below N (places): median of launch medians, IQR"] = [float(np.nanmedian(R.c_dist_med)), float(np.nanpercentile(R.c_dist_med, 25)), float(np.nanpercentile(R.c_dist_med, 75))]
cum = R.hit.copy(); orc = {}
for name, bs in (("fix A", ["A"]), ("fix A+B", ["A", "B"]), ("fix A+B+D", ["A", "B", "D"]), ("fix all", ["A", "B", "D", "C"])):
    orc[name] = lb((R.hit + R[bs].sum(1)) / R.n_voters)
res["oracle recall@N"] = orc
res["reverse: top-N people who did not vote"] = {"median upvotes 30d non-voters vs voters": [round(float(RV.n30_nonvoters_med.median()), 1), round(float(RV.n30_voters_med.median()), 1)],
    "share among 1,000 most active (mean)": round(float(RV.share_top1000.mean()), 3), "share who voted for another launch that day (mean)": round(float(RV.share_voted_other.mean()), 3)}
json.dump(res, open(os.path.join(OUTD, "who_backs_miss.json"), "w"), indent=1, default=float); print(json.dumps(res, default=float))
