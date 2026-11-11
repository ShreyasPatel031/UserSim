"""Website-deployable taste scorer with API embeddings (orchestrator 23:50Z Nov 11).
Product text is embedded with gemini-embedding-001 (Vertex or Gemini API, task_type SEMANTIC_SIMILARITY, 768-d; the 256-d
variant = first 256 dims renormalised, equal to outputDimensionality=256). Person side = the person's uses items embedded in the
same space, shipped as an anonymous bundle. Learned scorer = logistic regression on similarity features (plain numpy weights).
Harness check (leak-controlled uses sets, eval_sets_lenmatched, 4,000 random tasks, person-disjoint 2 folds): AUC of S2
(top-5 mean cosine) and the learned scorer (logistic; LightGBM shown for reference) with bge-small / bge-base / Gemini-768 /
Gemini-256, plus the shuffled-profile control for the learned scorer (personal = AUC - shuffled).
Features: top1, top5 mean, mean, share above the space's 99th-percentile random-pair similarity, log1p profile size.
    python gemini_bundle.py <uses2 dir> <outdir>
"""
import concurrent.futures as cf, json, os, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd

D, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
EP = ("https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/"
      "models/gemini-embedding-001:predict")
_tok = {"t": "", "at": 0}


def token():
    if time.time() - _tok["at"] > 300:
        _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
    return _tok["t"]


def embed_batch(texts):
    body = {"instances": [{"content": t, "task_type": "SEMANTIC_SIMILARITY"} for t in texts], "parameters": {"outputDimensionality": 768}}
    for i in range(6):
        try:
            req = urllib.request.Request(EP, json.dumps(body).encode(), {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
            j = json.load(urllib.request.urlopen(req, timeout=180))
            return np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32)
        except Exception as e:  # noqa: BLE001
            print("retry", i, str(e)[:120], flush=True); time.sleep(4 * (i + 1))
    raise RuntimeError("embedding failed")


P = pd.read_parquet(os.path.join(D, "export", "products.parquet")); pix = {s: i for i, s in enumerate(P.slug)}
Pe = pd.read_parquet(os.path.join(D, "export", "people.parquet"))
T = pd.read_parquet(os.path.join(D, "export", "eval_sets_lenmatched.parquet")).sample(4000, random_state=0)
uses = [sorted({pix[s] for k in ("stack", "review", "collection") for s in r[k] if s in pix}) for _, r in Pe.iterrows()]
need = set(i for u in uses for i in u)
for t in T.itertuples():
    need |= {pix[t.heldout]} | {pix[s] for s in t.negatives} | {pix[s] for s in t.profile}
    if t.other_profile is not None: need |= {pix[s] for s in t.other_profile if s in pix}
need |= set(rng.choice(len(P), 3000, replace=False).tolist())          # reference products for thresholds
need = np.array(sorted(need)); print("products to embed", len(need), flush=True)
ef = os.path.join(OUT, "gem768.npy")
if os.path.exists(ef):
    G = np.load(ef)
else:
    texts = [str(P.rich_text.iloc[i] or P.text.iloc[i])[:1200] for i in need]
    chunks = [texts[i:i + 200] for i in range(0, len(texts), 200)]
    with cf.ThreadPoolExecutor(4) as ex: parts = list(ex.map(embed_batch, chunks))
    G = np.vstack(parts); np.save(ef, G)
print("embedded", G.shape, flush=True)
gpos = {g: k for k, g in enumerate(need)}
norm = lambda M: M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
SP = {"gemini768": norm(G), "gemini256": norm(G[:, :256].copy())}
for nm, f in (("bge_small", "emb_small_rich.npy"), ("bge_base", "emb_base_rich.npy")):
    SP[nm] = np.load(os.path.join(D, f), mmap_mode="r")[need].astype(np.float32)
ref = np.array([gpos[i] for i in need[:3000]])


def feats(E, hi, prof, cand):
    S = E[cand] @ E[prof].T; Ss = np.sort(S, 1); k = min(5, S.shape[1])
    return np.c_[Ss[:, -1], Ss[:, -k:].mean(1), S.mean(1), (S > hi).mean(1), np.full(len(cand), np.log1p(len(prof)))]


from sklearn.linear_model import LogisticRegression
import lightgbm as lgb
people = T.person_id.unique(); fold = {p: i % 2 for i, p in enumerate(rng.permutation(people))}
res = {"design": __doc__.split("\n    python")[0], "tasks": 4000, "products_embedded": int(len(need)), "auc": {}}
models = {}
for nm, E in SP.items():
    rr = rng.choice(len(E), 2000, replace=False); hi = float(np.percentile(E[rr] @ E[rr[::-1]].T, 99))
    rows, crow = [], []
    for t in T.itertuples():
        cand = np.array([gpos[pix[t.heldout]]] + [gpos[pix[s]] for s in t.negatives]); prof = np.array([gpos[pix[s]] for s in t.profile])
        if not len(prof): continue
        y = np.r_[1, np.zeros(len(cand) - 1)]
        rows.append((t.task, t.person_id, feats(E, hi, prof, cand), y))
        op = [gpos[pix[s]] for s in (t.other_profile if t.other_profile is not None else []) if s in pix]
        if op: crow.append((t.task, t.person_id, feats(E, hi, np.array(op), cand), y))
    def stack(R):
        F = np.vstack([r[2] for r in R]); Y = np.concatenate([r[3] for r in R])
        tk = np.concatenate([[r[0]] * len(r[3]) for r in R]); pp = np.concatenate([[r[1]] * len(r[3]) for r in R]); return F, Y, tk, pp
    F, Y, TK, PP = stack(rows); Fc, Yc, TKc, PPc = stack(crow)
    fo = np.array([fold[p] for p in PP]); foc = np.array([fold[p] for p in PPc])
    mu, sd = F.mean(0), F.std(0) + 1e-9
    sc = {"S2 top5": F[:, 1].copy(), "learned logistic": np.zeros(len(Y)), "learned lgbm": np.zeros(len(Y))}; scc = np.zeros(len(Yc))
    for k in (0, 1):
        lr = LogisticRegression(C=1.0, max_iter=1000).fit((F[fo != k] - mu) / sd, Y[fo != k])
        sc["learned logistic"][fo == k] = lr.decision_function((F[fo == k] - mu) / sd); scc[foc == k] = lr.decision_function((Fc[foc == k] - mu) / sd)
        gb = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=200, verbose=-1, random_state=0).fit(F[fo != k], Y[fo != k])
        sc["learned lgbm"][fo == k] = gb.predict_proba(F[fo == k])[:, 1]

    def auc(v, y, tk, pp):
        out = {}
        df = pd.DataFrame({"v": v, "y": y, "tk": tk, "p": pp})
        for t_, g in df.groupby("tk", sort=False):
            tg = g.v[g.y == 1].iloc[0]; ng = g.v[g.y == 0]; out[t_] = (g.p.iloc[0], ((ng < tg).sum() + 0.5 * (ng == tg).sum()) / len(ng))
        s = pd.DataFrame(out.values(), index=out.keys(), columns=["p", "a"]); return s
    r = {}
    for m, v in sc.items():
        s = auc(v, Y, TK, PP); g = s.groupby("p").a.mean().to_numpy()
        bs = [g[rng.integers(0, len(g), len(g))].mean() for _ in range(1000)]
        r[m] = [round(float(g.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4), int(len(g))]
    s1 = auc(sc["learned logistic"], Y, TK, PP); s0 = auc(scc, Yc, TKc, PPc); j = s1.index.intersection(s0.index)
    d = (s1.a[j] - s0.a[j]).groupby(s1.p[j]).mean().to_numpy(); bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(1000)]
    r["learned logistic personal (AUC - shuffled)"] = [round(float(d.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]
    res["auc"][nm] = r; print(nm, r, flush=True)
    lr = LogisticRegression(C=1.0, max_iter=1000).fit((F - mu) / sd, Y)
    models[nm] = {"w": lr.coef_[0].tolist(), "b": float(lr.intercept_[0]), "mu": mu.tolist(), "sd": sd.tolist(), "hi": hi}
json.dump(res, open(os.path.join(OUT, "gemini_bundle_auc.json"), "w"), indent=1)

# ---------- bundle (Gemini space; dimension chosen by size/AUC: 256 if within 0.01 AUC of 768)
dim = 256 if res["auc"]["gemini256"]["learned logistic"][0] >= res["auc"]["gemini768"]["learned logistic"][0] - 0.01 else 768
E = SP[f"gemini{dim}"]; md = models[f"gemini{dim}"]
order = np.random.default_rng(0).permutation(len(Pe))
items = sorted({gpos[g] for i in order for g in uses[i]}); ipos = {g: k for k, g in enumerate(items)}
ptr, idx, nu = [0], [], []
for i in order:
    u = [ipos[gpos[g]] for g in uses[i]]; idx += u; ptr.append(len(idx)); nu.append(len(u))
IE = E[np.array(items)]; idx = np.array(idx, np.int32); ptr = np.array(ptr, np.int64)
w, b, mu, sd, hi = np.array(md["w"]), md["b"], np.array(md["mu"]), np.array(md["sd"]), md["hi"]


def person_scores(q):
    s = IE @ q; out = np.full(len(ptr) - 1, -1e9, np.float32)
    for j in range(len(out)):
        v = s[idx[ptr[j]:ptr[j + 1]]]
        if not len(v): continue
        vs = np.sort(v); f = np.array([vs[-1], vs[-5:].mean(), v.mean(), (v > hi).mean(), np.log1p(len(v))])
        out[j] = ((f - mu) / sd) @ w + b
    return out


R = E[ref]; thr = np.zeros(len(order), np.float32); allsc = np.vstack([person_scores(q) for q in R])   # [3000, people]
thr = np.percentile(allsc, 99, axis=0).astype(np.float32)
import re as _re
ROLES = {"dev": r"develop|engineer|programm|coder|software|full.?stack|backend|frontend|devops|\bcto\b", "design": r"design|\bux\b|\bui\b|creative|artist",
         "market": r"market|growth|seo|content|brand|social media", "founder": r"founder|\bceo\b|entrepreneur|indie ?hacker|maker|builder|bootstrap",
         "product": r"product manager|\bpm\b|product lead|head of product", "data_ai": r"\bai\b|machine learning|\bml\b|data scien|llm|research",
         "sales": r"sales|\bbd\b|business develop|revenue", "student": r"student|universit|college|learning", "invest": r"invest|\bvc\b|angel|partner at"}
roles = np.array([[int(bool(_re.search(p, Pe.headline_bio.iloc[i] or "", _re.I))) for p in ROLES.values()] for i in order], np.uint8)
bf = os.path.join(OUT, "person_bundle_gemini.npz")
np.savez_compressed(bf, item_emb=IE.astype(np.float16), person_ptr=ptr, person_items=idx, pct99=thr, roles=roles, role_names=np.array(list(ROLES)),
                    n_uses=np.array(nu, np.int32), w=w.astype(np.float32), b=np.float32(b), mu=mu.astype(np.float32), sd=sd.astype(np.float32),
                    hi=np.float32(hi), model=np.array("gemini-embedding-001"), task_type=np.array("SEMANTIC_SIMILARITY"), dim=np.int32(dim))
t0 = time.time(); _ = person_scores(R[0]); res["bundle"] = {"file": bf, "dim": dim, "items": int(len(items)), "people": int(len(order)),
                                                           "bytes": os.path.getsize(bf), "score_seconds_numpy_loop": round(time.time() - t0, 3)}
json.dump(res, open(os.path.join(OUT, "gemini_bundle_auc.json"), "w"), indent=1)
print(json.dumps(res["bundle"]), flush=True)
