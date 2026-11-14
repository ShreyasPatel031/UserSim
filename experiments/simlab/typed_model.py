"""Typed concerns / questions, step 4-5 (orchestrator 00:47Z Nov 14). Counts only.
Labels: launch-level set of concern types / question types present among its first 25 non-team comments (typed_label.py; taxonomy induced
on Jan-Feb only). Model: one logistic per type (L2, C=0.5) on the launch's own submitted text (TF-IDF of name + tagline + description,
1-2 grams, min_df 5, max 3000, fit on training months) + topic one-hots; month-forward (train on months before the test month; test months
Mar-Oct). Output per launch: probabilities, top-3 types. Metrics (test months): type-level p@3 (share of the 3 predicted types present) and
top-1, vs the CONSTANT top-3 (most frequent types in the training months), paired, day bootstrap; on all labelled launches and on those
with >= 1 labelled concern (question). Calibration: decile reliability pooled over types, Brier skill vs the training base rate.
    python typed_model.py <scratchpad> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.sparse import hstack, csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); TD = f"{SP}/typed"
T = json.load(open(f"{TD}/taxonomy.json")); CT = [c["id"] for c in T["concern_types"]]; QT = [c["id"] for c in T["question_types"]]
LB = pd.DataFrame([json.loads(l) for l in open(f"{TD}/labels.jsonl")]).drop_duplicates(["id", "i"])
def norm(k, t):   # flash-lite sometimes puts the type in 'kind' or drops the c_/q_ prefix
    k, t = str(k or ""), str(t or "")
    for cand in (t, k):
        for pre, kk, TY in (("c_", "concern", CT), ("q_", "question", QT)):
            if cand in TY: return kk, cand
            if pre + cand in TY and (k in (kk, cand) or cand == k): return kk, pre + cand
    for cand in (t, k):
        if "c_" + cand in CT: return "concern", "c_" + cand
        if "q_" + cand in QT: return "question", "q_" + cand
    return (k if k in ("concern", "question") else "other"), "other"
LB[["kind", "type"]] = [norm(k, t) for k, t in zip(LB.kind, LB.type)]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
L = L[L.id.isin(LB.id)].copy(); L["mon"] = L.day.str[:7]
L["txt"] = (L.name.fillna("") + ". " + L.tagline.fillna("") + ". " + L.description.fillna("")).str.slice(0, 2000)
def tops(t):
    try: return [str(x) for x in (json.loads(t) if isinstance(t, str) else list(t))]
    except Exception: return []
L["tp"] = L.topics.map(tops)
res = {"design": __doc__.split("\n    python")[0], "taxonomy": {"concern types": CT, "question types": QT}, "labelled launches": len(L),
       "label counts": LB.kind.value_counts().to_dict()}
def ci(v, days):
    v = np.asarray(v, float); dd = np.asarray(days); ud = np.unique(dd); idx = {d: np.flatnonzero(dd == d) for d in ud}
    bs = [v[np.concatenate([idx[d] for d in rng.choice(ud, len(ud))])].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
for kind, TY in (("concern", CT), ("question", QT)):
    Y = LB[LB.kind == kind].groupby("id").type.agg(set); L[f"Y_{kind}"] = L.id.map(Y).apply(lambda s: s if isinstance(s, set) else set())
    for t in TY: L[f"{kind}:{t}"] = L[f"Y_{kind}"].apply(lambda s: float(t in s))
    mons = sorted(L.mon.unique()); test = [m for m in mons if m >= "2026-03"]; P = np.full((len(L), len(TY)), np.nan); CONST = {}
    for m in test:
        tr = (L.mon < m).values; te = (L.mon == m).values
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=5, max_features=3000, sublinear_tf=True).fit(L.txt[tr])
        tv = sorted({x for s in L.tp[tr] for x in s}); ti = {x: k for k, x in enumerate(tv)}
        def X(mask):
            M = np.zeros((mask.sum(), len(tv)))
            for r, s in enumerate(L.tp[mask]):
                for x in s:
                    if x in ti: M[r, ti[x]] = 1
            return hstack([vec.transform(L.txt[mask]), csr_matrix(M)]).tocsr()
        Xtr, Xte = X(tr), X(te); base = L.loc[tr, [f"{kind}:{t}" for t in TY]].mean().values; CONST[m] = np.argsort(-base)[:3]
        for j, t in enumerate(TY):
            y = L.loc[tr, f"{kind}:{t}"].values
            P[te, j] = LogisticRegression(C=0.5, max_iter=1000).fit(Xtr, y).predict_proba(Xte)[:, 1] if 0 < y.sum() < len(y) else base[j]
    te = L.mon.isin(test).values; Yte = L.loc[te, [f"{kind}:{t}" for t in TY]].values; Pte = P[te]; days = L.day[te].values; mte = L.mon[te].values
    o3 = np.argsort(-Pte, 1)[:, :3]; c3 = np.array([CONST[m] for m in mte])
    pm = np.array([Yte[r, o3[r]].mean() for r in range(len(Yte))]); pc = np.array([Yte[r, c3[r]].mean() for r in range(len(Yte))])
    t1m = np.array([Yte[r, o3[r, 0]] for r in range(len(Yte))]); t1c = np.array([Yte[r, c3[r, 0]] for r in range(len(Yte))])
    has = Yte.sum(1) > 0; o = {"test launches": int(te.sum()), "with >= 1 labelled type": int(has.sum()),
        "type base rates (test, %)": {t: round(float(Yte[:, j].mean()) * 100, 1) for j, t in enumerate(TY)}}
    for nm, msk in (("all labelled launches", np.ones(len(Yte), bool)), (f"launches with >= 1 {kind}", has)):
        o[nm] = {"model p@3": ci(pm[msk], days[msk]), "constant p@3": ci(pc[msk], days[msk]), "model - constant p@3": ci(pm[msk] - pc[msk], days[msk]),
                 "model top-1": ci(t1m[msk], days[msk]), "constant top-1": ci(t1c[msk], days[msk]), "model - constant top-1": ci(t1m[msk] - t1c[msk], days[msk])}
    # calibration
    pf, yf = Pte.ravel(), Yte.ravel(); bins = np.quantile(pf, np.linspace(0, 1, 11)); k = np.clip(np.searchsorted(bins, pf, side="right") - 1, 0, 9)
    br = np.array([np.mean(Yte[L.mon[te].values == mm], 0) for mm in mte])  # placeholder overwritten below
    basep = np.array([L.loc[(L.mon < mm).values, [f"{kind}:{t}" for t in TY]].mean().values for mm in mte])
    bm, bb = np.mean((pf - yf) ** 2), np.mean((basep.ravel() - yf) ** 2)
    o["calibration"] = {"deciles (mean predicted %, observed %, n)": [[round(float(pf[k == b].mean()) * 100, 1), round(float(yf[k == b].mean()) * 100, 1), int((k == b).sum())] for b in range(10) if (k == b).any()],
                        "Brier model / base-rate": [round(float(bm), 4), round(float(bb), 4)], "Brier skill": round(float(1 - bm / bb), 3)}
    res[kind + "s"] = o
    pd.DataFrame(Pte, columns=TY).assign(id=L.id[te].values, day=days).to_parquet(f"{TD}/pred_{kind}.parquet")
json.dump(res, open(os.path.join(OUT, "typed_model.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k not in ("design",)}, default=float)[:6000])
