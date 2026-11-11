"""Uses track (2b, orchestrator P3 Nov 11): persona-card features in LightGBM on E5's uses harness v2 (pop-matched tasks).
Per (task, candidate) row:
  card_sim   TF-IDF cosine (fit on product texts) between the persona card (role, domain, tools_used, looks_for,
             platforms, summary) and the candidate's text
  avoid_sim  the same against the card's 'avoids'
  card_*     technical_depth, seniority (ordinal), price_sensitivity (ordinal), n_uses_in, n_ups_in
  prof_sim   TF-IDF cosine between the candidate and the mean vector of the task's profile items (content taste from
             the person's other uses items: a stand-in for E5's U taste, whose embeddings are not in tmp/e5/uses/)
  log_pop    log1p(pop_loo) (popularity with the person left out)
Cards were written without any held-out item (uses_sim.py card, frozen sha 1d9377a2). Person-disjoint 2-fold split
(by salted id), binary LightGBM, scored per task: AUC (share of negatives below the held-out), Hit@1, Hit@10, ties at
random; all tasks and pop decile <= 5. Paired bootstrap over tasks vs popularity and vs prof_sim+pop.
usage: USES_DIR=<dir> python uses_lgb.py -> results/uses_lgb.json"""
import json, os
import numpy as np, pandas as pd
import lightgbm as lgb
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

U = os.environ["USES_DIR"]; HERE = os.path.dirname(os.path.abspath(__file__))
SEN = {"student": 0, "junior": 1, "mid": 2, "senior": 3, "founder_exec": 4}; PRI = {"low": 0, "medium": 1, "high": 2}


def main():
    P = pd.read_parquet(f"{U}/products.parquet"); E = pd.read_parquet(f"{U}/{os.environ.get('EVAL', 'eval_sets.parquet')}")
    C = {}
    for l in open(f"{U}/cards.jsonl"):
        r = json.loads(l)
        if "card" in r:
            C[r["person_id"]] = r
    E = E[(E.neg_kind == "pop_matched") & E.person_id.isin(C)].reset_index(drop=True)
    six = {s: i for i, s in enumerate(P.slug)}
    vec = TfidfVectorizer(min_df=3, max_features=200000, ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
    XP = normalize(vec.fit_transform(P.text.fillna("").str[:1000]))
    pids = sorted(C); pix = {p: i for i, p in enumerate(pids)}
    j = lambda c, k: " ".join(c.get(k) or []) if isinstance(c.get(k), list) else str(c.get(k) or "")
    ctext = [" ".join([j(C[p]["card"], k) for k in ("role", "domain", "tools_used", "looks_for", "platforms", "summary")]) for p in pids]
    atext = [j(C[p]["card"], "avoids") for p in pids]
    XC = normalize(vec.transform(ctext)); XA = normalize(vec.transform(atext))
    rows = []
    for t in E.itertuples():
        cand = [t.heldout] + list(t.negatives); pop = [t.pop_loo_heldout] + list(t.pop_loo_negatives)
        for k, (s, pp) in enumerate(zip(cand, pop)):
            rows.append((t.task, t.person_id, six.get(s, -1), int(k == 0), float(pp)))
    R = pd.DataFrame(rows, columns=["task", "person", "pix", "y", "pop"])
    ok = R.pix >= 0
    ci = R.person.map(pix).values
    # row-wise cosine in chunks
    def rowcos(A, ai, Bm, bi):
        out = np.zeros(len(ai))
        for s in range(0, len(ai), 200000):
            a = A[ai[s:s + 200000]]; b = Bm[bi[s:s + 200000]]
            out[s:s + 200000] = np.asarray(a.multiply(b).sum(1)).ravel()
        return out
    pi = R.pix.clip(lower=0).values
    R["card_sim"] = np.where(ok, rowcos(XC, ci, XP, pi), np.nan); R["avoid_sim"] = np.where(ok, rowcos(XA, ci, XP, pi), np.nan)
    import scipy.sparse as sp
    g = R.groupby("task").indices
    prof_sim = np.full(len(R), np.nan)
    for t in E.itertuples():
        pr = [six[s] for s in t.profile if s in six]; ix = g[t.task]
        if not pr:
            continue
        cen = normalize(sp.csr_matrix(XP[pr].mean(0)))
        cc = R.pix.values[ix]; v = np.asarray((XP[np.clip(cc, 0, None)] @ cen.T).todense()).ravel()
        prof_sim[ix] = np.where(cc >= 0, v, np.nan)
    R["prof_sim"] = prof_sim
    for k, f in (("card_depth", lambda c: c.get("technical_depth")), ("card_sen", lambda c: SEN.get(c.get("seniority"))),
                 ("card_price", lambda c: PRI.get(c.get("price_sensitivity")))):
        m = {p: f(C[p]["card"]) for p in pids}; R[k] = R.person.map(m).astype(float)
    R["card_nuses"] = R.person.map({p: C[p]["n_uses_in"] for p in pids}).astype(float)
    R["card_nups"] = R.person.map({p: C[p]["n_ups_in"] for p in pids}).astype(float)
    R["log_pop"] = np.log1p(R["pop"].clip(lower=0))
    tl = P.text.fillna("").str.len().values; R["txt_len"] = np.where(ok, tl[R.pix.clip(lower=0).values], 0)   # E5 leak control
    dec = dict(zip(P.slug, P.pop_decile)); held = dict(zip(E.task, E.heldout)); low = {t: dec.get(h, 9) <= 5 for t, h in held.items()}
    fold = R.person.map(lambda p: int(p[2:4], 16) % 2).values
    CARD = ["card_sim", "avoid_sim", "card_depth", "card_sen", "card_price", "card_nuses", "card_nups"]
    V = {"length_only": ["txt_len"], "popularity": ["log_pop"], "card": CARD, "card+pop": CARD + ["log_pop"], "prof": ["prof_sim"],
         "prof+pop": ["prof_sim", "log_pop"], "prof+card+pop": ["prof_sim", "log_pop"] + CARD, "prof+card": ["prof_sim"] + CARD}
    rng = np.random.default_rng(0); scores = {}
    for nm, cols in V.items():
        s = np.zeros(len(R))
        for f in (0, 1):
            tr, te = fold != f, fold == f
            if len(cols) == 1:
                s[te] = R.loc[te, cols[0]].fillna(-1).values
                continue
            m = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=100, verbose=-1, n_jobs=4)
            m.fit(R.loc[tr, cols], R.y[tr]); s[te] = m.predict_proba(R.loc[te, cols])[:, 1]
        scores[nm] = s + rng.random(len(s)) * 1e-9
    per = []
    for nm, s in scores.items():
        D = pd.DataFrame({"task": R.task.values, "y": R.y.values, "s": s})
        hs = D[D.y == 1].set_index("task").s
        D["above"] = (D.s > D.task.map(hs)) & (D.y == 0); D["below"] = (D.s < D.task.map(hs)) & (D.y == 0)
        g2 = D.groupby("task").agg(above=("above", "sum"), below=("below", "sum"), n=("y", "size"))
        g2["auc"] = g2.below / (g2.n - 1); g2["hit1"] = (g2.above == 0).astype(float); g2["hit10"] = (g2.above < 10).astype(float)
        g2["scorer"] = nm; per.append(g2.reset_index())
    T = pd.concat(per); T["low"] = T.task.map(low)
    def b(x):
        x = np.asarray(x, float)
        return [round(float(x.mean()), 3)] + [round(float(v), 3) for v in np.percentile([x[rng.integers(0, len(x), len(x))].mean() for _ in range(2000)], [2.5, 97.5])] + [int(len(x))]
    res = {"eval": os.environ.get("EVAL", "eval_sets.parquet"), "tasks": int(T.task.nunique()), "note": "pop-matched negatives; person-disjoint 2-fold; prof_sim stands in for E5 U taste (no embeddings in tmp/e5/uses/)"}
    for sub, m in (("all", T.task.notna()), ("pop_decile_le5", T.low)):
        Q = T[m]; piv = {c: Q.pivot(index="task", columns="scorer", values=c) for c in ("auc", "hit1", "hit10")}
        res[sub] = {nm: {c: b(piv[c][nm]) for c in piv} for nm in V}
        for a, z in (("card+pop", "popularity"), ("prof+card+pop", "prof+pop"), ("card", "prof"), ("prof+card", "prof")):
            res[sub][f"{a} - {z}"] = {c: b(piv[c][a] - piv[c][z]) for c in piv}
    json.dump(res, open(os.path.join(HERE, "results", os.environ.get("OUT", "uses_lgb") + ".json"), "w"), indent=1)
    for sub in ("all", "pop_decile_le5"):
        for k, v in res[sub].items():
            print(sub, k, {c: v[c][:3] for c in v})


if __name__ == "__main__":
    main()
