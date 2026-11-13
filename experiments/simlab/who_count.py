"""Per-person count model + person-hit baselines (orchestrator 18:40Z Nov 13). Reuses who_choice.py's cubes (exec'd up to the arms).
Per person p, launch L, day d (history only):
  a_p   = share of the 60 prior launch days on which p voted (P(active))
  k_p   = mean daily vote count on those days (expected votes)
  cond  = P(p votes L | p active that day): logistic on the 30 prior days' voters, features = FULL (n30, n90, last, taste, fol, hun,
          back, wk, cf) + ln(1 + k_p); NOT normalised across the line-up, so a mass voter can be likely for many launches.
Arms (expected backers E(L) = sum over people, ranked per launch for recall):
  COUNT       P = a_p x cond
  HYBRID      P = sqrt(COUNT x min(1, k_p x s_pL)), s = softmax choice share (taste+cf+team+clean prior, who_choice.py)
  CHOICE      P = min(1, k_p x s_pL) (the who_choice.py softmax+prior arm, recomputed here for the same rows)
R-precision (recall when the list is as long as the launch's real number of held voters) is reported because recall at N = round(E)
depends on calibration (a larger E gives a longer list). Metrics as before (recall at N / 2N, calibration, launch top 3/5/10 vs tie-averaged placebo and clean), plus:
  person-level top-3 hit for CHOICE vs baselines on the same voter person-days: (a) everyone gets the clean_nosite order;
  (b) the person's team ties only (back + fol + hun; ties broken by a fixed random draw); (c) ORACLE: final daily rank order.
  Splits of recall and person hit by voter type that day: 1 vote, 2-4, 5+. Counts only.
    python who_count.py <store dir> <clean_live_rows_nosite.parquet> <launches dir> <salt dir> <honest_preds_v2.parquet> <out dir>
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); src = open(os.path.join(HERE, "who_choice.py")).read()
exec(src[src.index("import os, sys, json, time"):src.index("def sm(z)")])
from sklearn.linear_model import LogisticRegression as LR
def sm(z): z = z - z.max(1, keepdims=True); e = np.exp(z); return e / e.sum(1, keepdims=True)
def hist(people, d):
    w = [x for x in lday_all if x < d][-60:]; win = set(w); sub = dcount[dcount.index.get_level_values(1).isin(win)]
    tot = sub.groupby(level=0).sum(); act = sub.groupby(level=0).size()
    return np.array([act.get(p, 0) / max(len(w), 1) for p in people]), np.array([tot.get(p, 0) / max(act.get(p, 1), 1) for p in people])
# training data for cond: voters of each prior day (TR holds voters only) with ln(1+k) appended
KTR = {}
for d in TR:
    c = day_cols(d)
    if c is None: continue
    act, out = c; ids = [i for i, _ in out]; vot = U[U.lday == d].groupby("person_id").target_id.agg(set).to_dict(); keep = np.array([p in vot for p in act.index])
    KTR[d] = hist(act.index[keep], d)[1]
print("k for training", round(time.time() - t0), flush=True)
FULLC = ["n30", "n90", "last", "taste", "fol", "hun", "back", "wk", "cf"]; CH = ["taste", "cf", "back", "hun", "fol", "prior"]
def fit_cond(days):
    Xs, ys = [], []
    for d in days:
        X, Y = TR[d]; k = KTR[d]; Z = np.concatenate([X[:, :, [FI[c] for c in FULLC]], np.broadcast_to(np.log1p(k)[:, None, None], (X.shape[0], X.shape[1], 1))], axis=2)
        Xs.append(Z.reshape(-1, Z.shape[2])); ys.append(Y.reshape(-1))
    return LR(max_iter=500).fit(np.vstack(Xs), np.concatenate(ys))
rows, ph = [], []
Ecount, Ehyb, Echo = {}, {}, {}
for d in DAYS:
    if TE[d] is None: continue
    trd = [x for x in sorted(TR) if x < d][-30:]; m = fit_cond(trd); w = fit_logit(trd, CH)
    act, ids, X, Y = TE[d]; a, k = hist(act.index, d); kreal = Y.sum(1)
    Z = np.concatenate([X[:, :, [FI[c] for c in FULLC]], np.broadcast_to(np.log1p(k)[:, None, None], (X.shape[0], X.shape[1], 1))], axis=2)
    cond = m.predict_proba(Z.reshape(-1, Z.shape[2]))[:, 1].reshape(X.shape[0], X.shape[1])
    S = sm(X[:, :, [FI[c] for c in CH]] @ w); Pc = a[:, None] * cond; Pch = np.minimum(1, k[:, None] * S); Ph = np.sqrt(Pc * Pch)
    vtype = np.where(kreal == 1, "1", np.where(kreal <= 4, "2-4", "5+"))
    for nm, P, EE in (("COUNT", Pc, Ecount), ("HYBRID", Ph, Ehyb), ("CHOICE", Pch, Echo)):
        for j, i in enumerate(ids):
            EE[i] = float(P[:, j].sum()); v = Y[:, j] > 0
            if v.sum():
                o = np.argsort(-P[:, j]); N = max(1, int(round(P[:, j].sum()))); inN = np.zeros(len(o), bool); inN[o[:N]] = True; in2N = np.zeros(len(o), bool); in2N[o[:2 * N]] = True
                nv = int(v.sum()); rp = v[o[:nv]].mean()
                rows.append({"arm": nm, "id": i, "rprec": rp, "r1": inN[v].mean(), "r2": in2N[v].mean(), **{f"r1_{t}": (inN[v & (vtype == t)].mean() if (v & (vtype == t)).any() else np.nan) for t in ("1", "2-4", "5+")}})
    # person-level top-3 hit on voter person-days
    vm = kreal > 0; cl = np.array([prior_s.get(i, 0) for i in ids]); fr = np.array([-float(D.loc[D.id == i, "rank"].iloc[0]) for i in ids])
    tie = X[:, :, FI["back"]] + X[:, :, FI["fol"]] + X[:, :, FI["hun"]] + rng.random(X.shape[:2]) * 1e-3
    for r in np.flatnonzero(vm):
        y = Y[r] > 0; o = {}
        for nm, sc in (("CHOICE (softmax + clean prior)", S[r]), ("COUNT cond", cond[r]), ("(a) clean order for everyone", cl), ("(b) team ties only", tie[r]), ("(c) ORACLE final rank order", fr)):
            o[nm] = y[np.argsort(-sc)[:3]].sum() / y.sum()
        ph.append({"type": vtype[r], **o})
    print(d, round(time.time() - t0), flush=True)
R = pd.DataFrame(rows); PH = pd.DataFrame(ph)
res = {"design": __doc__.split("\n    python")[0], "days": DAYS, "placebo (tie-averaged) top3/5/10": PL.mean(0).round(1).tolist(), "clean_nosite top3/5/10": CL.mean(0).round(1).tolist()}
for nm, EE in (("COUNT", Ecount), ("HYBRID", Ehyb), ("CHOICE", Echo)):
    D["E"] = D.id.map(EE).fillna(0); A = np.array([dm(D[D.day == d], "E") for d in DAYS]); g = R[R.arm == nm]
    cal = D[D.E > 0].assign(v=D.id.map(votes).astype(float)); cal = cal[cal.v > 0]
    res[nm] = {"R-precision (list size = the launch's real held-voter count; calibration-free)": lb(g.rprec), "recall@N": lb(g.r1), "recall@2N": lb(g.r2), "recall@N by voter type (1 / 2-4 / 5+ votes that day)": {t: lb(g[f"r1_{t}"]) for t in ("1", "2-4", "5+")},
               "top3/5/10": A.mean(0).round(1).tolist(), "vs placebo": pdiff(A, PL), "vs clean": pdiff(A, CL),
               "calibration median E/displayed, Spearman": [round(float((cal.E / cal.v).median()), 3), round(float(spearmanr(cal.E, cal.v).correlation), 3)]}
cols = [c for c in PH.columns if c != "type"]
res["person-level top-3 hit (same voter person-days)"] = {c: lb(PH[c]) for c in cols}
res["person-level top-3 hit by voter type"] = {t: {c: lb(PH[PH.type == t][c]) for c in cols} for t in ("1", "2-4", "5+")}
res["CHOICE - (a) clean order, person hit"] = lb(PH["CHOICE (softmax + clean prior)"] - PH["(a) clean order for everyone"])
json.dump(res, open(os.path.join(OUT, "who_count.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
