"""Product-specific "who" vs the best constant (website agent / orchestrator, Nov 12). who_segments_v1 turned out near-constant (the
same #1 segment for every launch). Reuses who_learn.py's data and truths (IDX12 segments, day lift) and evaluates, month-forward:
  CONST    top 3 by the mean training log day-lift (the best constant list)
  RIDGE    top 3 by the ridge prediction (= who_segments_v1 recipe)
  DEV      top 3 by ridge prediction minus the training mean (how much MORE than usual this launch draws a segment)
  RETR30D  mean log day-lift of the 30 most similar earlier launches minus the training mean
Truths: DAY (day lift > 1.5, >= 3 voters) and ABOVE-USUAL (day lift >= 1.5 x the segment's mean training day lift, >= 3 voters).
Also: share of launches whose top-3 differs from the method's most common set, p@3 on those; and a variable-length list showing only
segments with predicted lift > 1 (precision and mean length).
    python who_fix.py <ph-website worktree> <scratchpad> <who_eval dir> <out dir>
"""
import os, sys
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "who_learn.py")).read().split('if os.environ.get("EXPORT")')[0]
src = src.split('import glob, json, os, sys', 1)[1]
exec("import glob, json, os, sys\n" + src)
from collections import Counter  # noqa: E402
rows = []; pool_k = np.array([k for k in LIFT_D if L.id.iat[k] in emb_of]); PE2 = np.vstack([emb_of[L.id.iat[k]] for k in pool_k]); FITS = {}
for qi, i in enumerate(S_all):
    k = lix[i]
    if k not in LIFT_D: continue
    m0 = np.datetime64(L.day.iat[k][:7] + "-01").astype(np.int64); tr = dnum[pool_k] < m0
    if m0 not in FITS:
        Y = np.log(np.vstack([LIFT_D[j] for j in pool_k[tr]]) + 0.05); FITS[m0] = (Ridge(alpha=10.0).fit(PE2[tr], Y), Y.mean(0), np.exp(Y).mean(0))
    rg, mu, usual = FITS[m0]; q = QP[qi]; pr = rg.predict(q[None])[0]
    sims = PE2[tr] @ q; nb = np.argsort(-sims)[:30]; retr = np.log(np.vstack([LIFT_D[j] for j in pool_k[tr][nb]]) + 0.05).mean(0)
    lift, c = LIFT_D[k], VC[k]; tD = set(np.flatnonzero((lift > 1.5) & (c >= 3)).tolist()); tU = set(np.flatnonzero((lift >= 1.5 * usual) & (c >= 3)).tolist())
    lists = {"CONST": list(np.argsort(-mu)[:3]), "RIDGE": list(np.argsort(-pr)[:3]), "DEV": list(np.argsort(-(pr - mu))[:3]), "RETR30D": list(np.argsort(-(retr - mu))[:3])}
    r = {"id": i}
    for nm, p in lists.items():
        r[f"{nm}|set"] = tuple(sorted(p))
        for tn, t in (("DAY", tD), ("ABOVE", tU)):
            r[f"{nm}|{tn}|p3"] = np.mean([x in t for x in p]); r[f"{nm}|{tn}|hit3"] = float(any(x in t for x in p))
        r[f"{nm}|lift1"] = lift[p[0]]; r[f"{nm}|rel1"] = lift[p[0]] / usual[p[0]]
    show = np.flatnonzero(np.exp(pr) - 0.05 > 1); r["show_n"] = len(show); r["show_prec_DAY"] = np.mean([x in tD for x in show]) if len(show) else np.nan
    showd = np.flatnonzero(np.exp(pr - mu) > 1.25); r["dev_show_n"] = len(showd); r["dev_show_prec_ABOVE"] = np.mean([x in tU for x in showd]) if len(showd) else np.nan
    rows.append(r)
D = pd.DataFrame(rows)
def mb(v, B=4000, sc=100):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * sc, 2), round(float(np.percentile(bs, 2.5)) * sc, 2), round(float(np.percentile(bs, 97.5)) * sc, 2), int(len(v))]
res = {"design": __doc__.split("\n    python")[0], "launches": int(len(D)), "methods": {}}
for nm in ("CONST", "RIDGE", "DEV", "RETR30D"):
    sets = D[f"{nm}|set"]; modal = Counter(sets).most_common(1)[0][0]; diff = sets != modal
    o = {"distinct_top3_sets": int(sets.nunique()), "share_differs_from_modal": round(float(diff.mean()), 3), "distinct_top1": int(D[f"{nm}|set"].map(lambda s: s).nunique())}
    for tn in ("DAY", "ABOVE"):
        o[f"{tn} p3"] = mb(D[f"{nm}|{tn}|p3"]); o[f"{tn} hit3"] = mb(D[f"{nm}|{tn}|hit3"]); o[f"{tn} p3 where set differs from modal"] = mb(D.loc[diff, f"{nm}|{tn}|p3"])
        if nm != "CONST": o[f"{tn} p3 - CONST (paired)"] = mb(D[f"{nm}|{tn}|p3"] - D[f"CONST|{tn}|p3"])
    o["real day lift top1"] = mb(D[f"{nm}|lift1"], sc=1); o["real lift / usual top1"] = mb(D[f"{nm}|rel1"], sc=1)
    res["methods"][nm] = o
res["RIDGE show only pred lift > 1"] = {"mean shown": round(float(D.show_n.mean()), 2), "share launches showing none": round(float((D.show_n == 0).mean()), 3), "precision DAY": mb(D.show_prec_DAY)}
res["DEV show only pred above-usual > 1.25"] = {"mean shown": round(float(D.dev_show_n.mean()), 2), "share none": round(float((D.dev_show_n == 0).mean()), 3), "precision ABOVE": mb(D.dev_show_prec_ABOVE)}
json.dump(res, open(os.path.join(OUT, "who_fix.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
