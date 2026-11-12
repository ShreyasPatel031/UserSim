"""Export launch_band_page_v2 (only after band_facts.py passed: S beats B0 on the 856 with the interval above 0 and keeps its sign on
the fresh 130). Variant exported: S_no_testimonial (testimonial / logo words left out: they can grow after launch; the gain is the
same). Refit on every page read (train + held + fresh): b0 = d_both (page + PH rows), stack ridge on [37-2 facts, retr30 (5), topic
prior, b0] with b0 5-fold out-of-fold, alpha as chosen in the test run; cuts / bands from 5-fold OOF stack scores.
Writes <out>/launch_band_page_v2.json + launch_band_page_v2_pool.npz and checks band_v2_score.score_v2 reproduces the in-script scores.
    python band_facts_export.py <scratchpad> <launch_band_page_v1.json> <out dir> <band_facts.json from the test run>
"""
import os, sys, json
SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "band_facts.py")).read().split("# ---------- B0")[0]
TESTRES = sys.argv[4]; sys.argv = sys.argv[:4]; os.environ["EXPORT"] = "1"
exec(SRC)   # reads, raw-html facts, helpers (L, D, FCOLS, TESTI, TW, LEAK, byid, VOCAB, ...)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import band_v2_score as BV  # noqa: E402
D = D.reset_index(drop=True)
tok = lambda t: re.findall(r"\b[a-z0-9]+\b", t)
def terms(n, t, d, tp):
    w = tok((f"{n}. {t}. {d} " + " ".join(tp)).lower()); return w + [a + " " + b for a, b in zip(w, w[1:])]
def build_vocab(T, max_terms=8000, min_df=3):
    df = Counter(t for ts in T for t in set(ts)); n = len(T); keep = [t for t, c in df.most_common() if c >= min_df][:max_terms]
    return {t: math.log((1 + n) / (1 + df[t])) + 1 for t in keep}
def tfidf(T, idf):
    ix = {t: k for k, t in enumerate(idf)}; data, ri, ci = [], [], []
    for r, ts in enumerate(T):
        c = Counter(t for t in ts if t in ix); x = {t: (1 + math.log(v)) * idf[t] for t, v in c.items()}; nm = math.sqrt(sum(v * v for v in x.values())) or 1.0
        for t, v in x.items(): data.append(v / nm); ri.append(r); ci.append(ix[t])
    return sparse.csr_matrix((data, (ri, ci)), shape=(len(T), len(idf)))
def dense(Rx): return np.array([[float(t in tp) for t in VOCAB] + [math.log1p(len(d)), math.log1p(len(tg)), float(len(tp))] for d, tg, tp in zip(Rx.desc, Rx.tagline, Rx.topics)], float)
def rows(Dx, src):
    if src == 1: Rx = pd.DataFrame({"name": Dx.name.values, "tagline": Dx.tagline.values, "desc": Dx.desc_long.values, "topics": Dx.topics.values})
    else: Rx = pd.DataFrame({"name": [byid[i].name or "" for i in Dx.id], "tagline": [byid[i].tagline or "" for i in Dx.id], "desc": [byid[i].description or "" for i in Dx.id], "topics": Dx.ptop.values})
    Rx["src"] = float(src); Rx["y"] = Dx.y.values; Rx["terms"] = [terms(*x) for x in zip(Rx.name, Rx.tagline, Rx.desc, Rx.topics)]; return Rx
def fit(Rx):
    idf = build_vocab(Rx.terms.tolist()); De = dense(Rx); mu, sd = De.mean(0), De.std(0) + 1e-9
    X = sparse.hstack([tfidf(Rx.terms.tolist(), idf), sparse.csr_matrix((De - mu) / sd), sparse.csr_matrix(Rx[["src"]].values)]).tocsr(); return idf, mu, sd, Ridge(alpha=3.0).fit(X, Rx.y.values)
def score(M, Rx):
    idf, mu, sd, m = M; return m.predict(sparse.hstack([tfidf(Rx.terms.tolist(), idf), sparse.csr_matrix((dense(Rx) - mu) / sd), sparse.csr_matrix(Rx[["src"]].values)]).tocsr())
both = lambda Dx: pd.concat([rows(Dx, 1), rows(Dx, 0)], ignore_index=True)
# b0 on everything (as served) + OOF for the stack
M = fit(both(D)); idf, mu0, sd0, m0 = M; nV = len(idf); co = m0.coef_
lb = {"vocab": {t: [idf[t], float(co[k])] for k, t in enumerate(idf)}, "topics_order": VOCAB, "dense_mean": list(mu0), "dense_sd": list(sd0),
      "dense_coef": list(co[nV:nV + len(mu0)]), "intercept": float(m0.intercept_ + co[-1] * 1.0)}
b0_oof = np.zeros(len(D))
for a, b in KFold(5, shuffle=True, random_state=0).split(D): b0_oof[b] = score(fit(both(D.iloc[a])), rows(D.iloc[b], 1))
# retrieval pool: every ranked launch, vocab on all PH text
ph_terms = [terms(n or "", t or "", d or "", []) for n, t, d in zip(L.name, L.tagline, L.description)]
RIDF = build_vocab(ph_terms, max_terms=20000); Xpool = tfidf(ph_terms, RIDF).astype(np.float32); pday = L.day.values; prp = L.rp.values; py = L.y.values
Q = tfidf([terms(n, t, d, []) for n, t, d in zip(D.name, D.tagline, D.desc_long)], RIDF); Sm = (Q @ Xpool.T).toarray().astype(np.float32); RR = []
for r in range(len(D)):   # training rows: strictly earlier pool, as in the test
    s = np.where(pday < D.day.iat[r], Sm[r], -1.0); o = np.argsort(-s)[:30]; o = o[s[o] > -1]; w = np.clip(s[o], 1e-4, None)
    RR.append([prp[o].mean(), (w * prp[o]).sum() / w.sum(), (w * py[o]).sum() / w.sum(), s[o].mean(), s[o[0]]] if len(o) else [np.nan] * 5)
RR = np.array(RR, float)
# topic prior for serving: all launches; for training rows: months strictly before (as tested)
gm_all = L.rp.mean(); c_, s_ = Counter(), Counter()
for tp, r in zip(L.ptop, L.rp):
    for t in tp: c_[t] += 1; s_[t] += r
TPRI = {t: (s_[t] + 20 * gm_all) / (c_[t] + 20) for t in c_} | {"_global": float(gm_all)}
g_all = {}
for mon in sorted(D.day.str[:7].unique()):
    E = L[L.day < mon + "-01"]; gm = E.rp.mean(); c, s2 = Counter(), Counter()
    for tp, r in zip(E.ptop, E.rp):
        for t in tp: c[t] += 1; s2[t] += r
    g_all[mon] = (gm, {t: (s2[t] + 20 * gm) / (c[t] + 20) for t in c})
tpr = np.array([np.mean([g_all[d[:7]][1].get(t, g_all[d[:7]][0]) for t in tp]) for d, tp in zip(D.day, D.topics)])
FX = [c for c in FCOLS if c not in TESTI]
X = np.hstack([D[FX].values.astype(float), RR, tpr[:, None], b0_oof[:, None]]); y = D.y.values
mu, sd = np.nanmean(X, 0), np.nanstd(X, 0) + 1e-9; f = lambda Z: np.nan_to_num((Z - mu) / sd)
AL = json.load(open(TESTRES))["stack_info"]["S_no_testimonial"]["alpha"]
m = Ridge(alpha=AL).fit(f(X), y); oof = np.zeros(len(y))
for a, b in KFold(5, shuffle=True, random_state=0).split(X): oof[b] = Ridge(alpha=AL).fit(f(X[a]), y[a]).predict(f(X[b]))
cuts = list(np.percentile(oof, np.arange(1, 100))); bands = []
for q in range(10):
    lo, hi = np.percentile(oof, [q * 10, (q + 1) * 10]); g = (oof >= lo) & ((oof < hi) if q < 9 else (oof <= hi))
    bands.append({"daily_rank_p10_p50_p90": [float(x) for x in np.percentile(D["rank"].values[g], [10, 50, 90])]})
T = json.load(open(TESTRES))
bundle = {"version": "launch_band_page_v2", "built": "2026-11-12", "trained_on": f"{len(D)} page reads (launches through 2026-11-10) + their PH rows",
          "how_to_score": "experiments/simlab/band_v2_score.py score_v2(bundle, pool, read, raw_html) on branch claude/person-model-v2",
          "inputs": "the site's page read (name, tagline, summary, page_excerpt, topics) + the raw HTML of the fetched page (optional; HTML facts fall back to training means)",
          "validation": {"pooled_856_minus_v1_recipe": T["pooled_856"]["S_no_testimonial"], "fresh_130": T["fresh_130"]["S_no_testimonial"], "held_726": T["held_sep_oct"]["S_no_testimonial"],
                         "b0_pooled": T["pooled_856"]["B0"], "note": "Spearman of the score with -rank; minus_B0 = paired launch bootstrap vs the d_both band (v1 recipe)"},
          "caveats": ["held pages were fetched up to 8 weeks after launch; fresh pages ~1-15 days", "testimonial / logo words excluded (may grow after launch)",
                      "retrieval pool = every ranked PH launch through Nov 10: a page of an already-launched product retrieves itself"],
          "b0": lb, "facts": FX, "word_facts": {k: r.pattern for k, r in TW.items() if k not in TESTI}, "retrieval_idf": RIDF, "retrieval_index": {t: k for k, t in enumerate(RIDF)},
          "topic_prior": TPRI, "stack": {"order": FX + ["r_rp", "r_rpw", "r_yw", "r_sim", "r_sim1", "topic_prior", "b0"], "mu": [float(v) for v in mu], "sd": [float(v) for v in sd],
                                         "coef": [float(v) for v in m.coef_], "intercept": float(m.intercept_), "alpha": AL, "target": "ln(1+votes)"},
          "score_percentile_cuts": [float(c) for c in cuts], "bands": bands}
OUT = sys.argv[3]; json.dump(bundle, open(os.path.join(OUT, "launch_band_page_v2.json"), "w"))
Xp = Xpool.tocsr(); np.savez_compressed(os.path.join(OUT, "launch_band_page_v2_pool.npz"), indptr=Xp.indptr.astype(np.int32), indices=Xp.indices.astype(np.int32),
                                          data=Xp.data.astype(np.float16), rp=prp.astype(np.float16), y=py.astype(np.float16))
# check: reference scorer vs in-script on 25 fresh rows (serving pool = all launches; in-script check uses the same all-launch pool)
pool = np.load(os.path.join(OUT, "launch_band_page_v2_pool.npz")); FH = {}
for l in open(os.path.join(SP, "band_v2/fresh_html.jsonl")):
    x = json.loads(l); FH[x["id"]] = x.get("html") or ""
FKr = {k.split("|", 1)[1]: v["read"] for k, v in json.load(open(os.path.join(SP, "try_fixes/cache.json"))).items() if k.startswith("p|") and "read" in v}
dif = []
for i in list(D[D.set == "fresh"].id)[:25]:
    r = D[D.id == i].iloc[0]; ref = BV.score_v2(bundle, pool, FKr[i], FH.get(i, ""))
    so = np.argsort(-(Q[D.index[D.id == i][0]] @ Xpool.T).toarray()[0])[:30]; sv = (Q[D.index[D.id == i][0]] @ Xpool.T).toarray()[0][so]; w = np.clip(sv, 1e-4, None)
    rr = [prp[so].mean(), (w * prp[so]).sum() / w.sum(), (w * py[so]).sum() / w.sum(), sv.mean(), sv[0]]
    xi = np.hstack([r[FX].values.astype(float), rr, [np.mean([TPRI.get(t, TPRI["_global"]) for t in r.topics])], [BV.b0_score(lb, r["name"], r.tagline, r.desc_long, r.topics)]])
    dif.append(abs(float(m.predict(f(xi[None]))[0]) - ref["score"]))
print("reference scorer max abs diff (25 fresh rows):", round(max(dif), 4), "size MB json", round(os.path.getsize(os.path.join(OUT, "launch_band_page_v2.json")) / 1e6, 1),
      "pool MB", round(os.path.getsize(os.path.join(OUT, "launch_band_page_v2_pool.npz")) / 1e6, 1))
