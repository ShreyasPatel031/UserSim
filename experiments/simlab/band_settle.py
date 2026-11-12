"""Settle the page-trained band (orchestrator 08:35Z Nov 12). Train on launches up to Aug 31 2026, test on Sep + Oct held page reads
(pages fetched Oct 25, within ~8 weeks of launch) pooled with the 130 fresh Oct 27 - Nov 10 reads. Arms, all with _band_score's exact
features (band_page_export.py) and scored through the site's own try_sim._band_score:
  (a) PH     trained on PH-description rows only (the launch_band.json recipe); served the page read's name / tagline / summary
  (b) PAGE   trained on page rows only; served name / tagline / summary + excerpt[:1500]
  (d) BOTH   page + PH rows with a source flag (folded into the intercept); served like (b)
Cuts / rank bands from 5-fold out-of-fold training scores of the served input type. Paired launch-bootstrap Spearman difference vs (a)
with -rank, coverage, width; split by fetch lag (Sep, Oct, fresh) and without pages that mention Product Hunt. If (d) or (b) clears
zero pooled AND keeps its sign on the 130 fresh: retrain on everything and export (band_page_export.py).
    python band_settle.py <ph-website worktree> <scratchpad> <band_page out dir> <out dir>
"""

import json, math, os, re, sys
from collections import Counter
import numpy as np, pandas as pd
from scipy import sparse
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

WT, SP, BP = sys.argv[1:4]; rng = np.random.default_rng(0)
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(SP, "gcp_key.json")); os.environ["TRY_SIGNING_KEY"] = "local-dummy-key-for-offline-eval-0123456789"
sys.path[:0] = [WT, os.path.join(WT, "src")]
from mvp.ph_site import try_sim, gcs  # noqa: E402
import glob  # noqa: E402
LB0 = gcs.read_json("results/web/launch_band.json"); VOCAB = try_sim.index()["meta"]["vocab"]
LEAK = re.compile(r"(?i)product\s*hunt|product of the (day|week|month)|#\s*1\s*product|upvote")
K = json.load(open(os.path.join(BP, "cache.json")))
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna()].copy(); L["id"] = L.id.astype(str); byid = {r.id: r for r in L.itertuples()}
phtop = lambda s: [t for t in (json.loads(s) if isinstance(s, str) and s.startswith("[") else []) if t in VOCAB][:4] or ["Productivity"]
rows = []
for i, v in K.items():
    if "fail" in v or i not in byid: continue
    r = byid[i]; y = math.log1p(float(r.votes))
    rows.append({"id": i, "src": 1, "name": v.get("name") or "", "tagline": v.get("tagline") or "", "desc": (v.get("summary") or "") + " " + (v.get("page_excerpt") or "")[:1500],
                 "topics": [t for t in (v.get("topics") or []) if t in VOCAB][:4] or ["Productivity"], "y": y, "rank": float(r.daily_rank), "votes": float(r.votes)})
    rows.append({"id": i, "src": 0, "name": r.name or "", "tagline": r.tagline or "", "desc": r.description or "", "topics": phtop(r.topics), "y": y, "rank": float(r.daily_rank), "votes": float(r.votes)})
D = pd.DataFrame(rows); print("rows", len(D), "page rows", int(D.src.sum()), flush=True)
tok = lambda t: re.findall(r"\b[a-z0-9]+\b", t)
def terms(n, t, d, tp):
    w = tok((f"{n}. {t}. {d} " + " ".join(tp)).lower()); return w + [a + " " + b for a, b in zip(w, w[1:])]
D["terms"] = [terms(*x) for x in zip(D.name, D.tagline, D.desc, D.topics)]


def build_vocab(T, max_terms=8000, min_df=3):
    df = Counter(t for ts in T for t in set(ts)); n = len(T)
    keep = [t for t, c in df.most_common() if c >= min_df][:max_terms]
    return {t: math.log((1 + n) / (1 + df[t])) + 1 for t in keep}


def tfidf(T, idf):
    ix = {t: k for k, t in enumerate(idf)}; data, ri, ci = [], [], []
    for r, ts in enumerate(T):
        c = Counter(t for t in ts if t in ix); x = {t: (1 + math.log(v)) * idf[t] for t, v in c.items()}; nm = math.sqrt(sum(v * v for v in x.values())) or 1.0
        for t, v in x.items(): data.append(v / nm); ri.append(r); ci.append(ix[t])
    return sparse.csr_matrix((data, (ri, ci)), shape=(len(T), len(idf)))


def dense(Dx):
    return np.array([[float(t in tp) for t in VOCAB] + [math.log1p(len(d)), math.log1p(len(tg)), float(len(tp))] for d, tg, tp in zip(Dx.desc, Dx.tagline, Dx.topics)], float)


def fit(Dx):
    idf = build_vocab(Dx.terms.tolist()); Xs = tfidf(Dx.terms.tolist(), idf); De = dense(Dx); mu, sd = De.mean(0), De.std(0) + 1e-9
    X = sparse.hstack([Xs, sparse.csr_matrix((De - mu) / sd), sparse.csr_matrix(Dx[["src"]].values.astype(float))]).tocsr()
    m = Ridge(alpha=3.0).fit(X, Dx.y.values); return idf, mu, sd, m


def score_model(idf, mu, sd, m, Dx):
    X = sparse.hstack([tfidf(Dx.terms.tolist(), idf), sparse.csr_matrix((dense(Dx) - mu) / sd), sparse.csr_matrix(Dx[["src"]].values.astype(float))]).tocsr(); return m.predict(X)



OUT = sys.argv[4]; os.makedirs(OUT, exist_ok=True)
D["day"] = D.id.map(lambda i: byid[i].day); TRm = D.day <= "2026-08-31"
def page_serve_rows(names, tags, descs, tops):
    return pd.DataFrame({"name": names, "tagline": tags, "desc": descs, "topics": tops})
FK = json.load(open(os.path.join(SP, "try_fixes/cache.json")))
TE = []
for i, v in K.items():                                         # held Sep / Oct page reads
    if "fail" in v or i not in byid or not ("2026-09-01" <= byid[i].day <= "2026-10-24"): continue
    TE.append({"id": i, "set": byid[i].day[:7], "name": v.get("name") or "", "tagline": v.get("tagline") or "", "summary": v.get("summary") or "", "excerpt": v.get("page_excerpt") or "",
               "topics": [t for t in (v.get("topics") or []) if t in VOCAB][:4] or ["Productivity"]})
for k, v in FK.items():                                        # fresh reads
    if not k.startswith("p|") or "read" not in v: continue
    i = k.split("|", 1)[1]; rd = v["read"]
    if i not in byid: continue
    TE.append({"id": i, "set": "fresh", "name": rd.get("name") or "", "tagline": rd.get("tagline") or "", "summary": rd.get("summary") or "", "excerpt": LEAK.sub(" ", rd.get("page_excerpt") or ""),
               "topics": [t for t in (rd.get("topics") or []) if t in VOCAB][:4] or ["Productivity"]})
RAWPH = {}
for l in open(os.path.join(SP, "fame/sites.jsonl")):
    x = json.loads(l)
    if x.get("html"): RAWPH[str(x["id"])] = bool(re.search(r"(?i)product\s*hunt|producthunt", x["html"]))
for k, v in FK.items():
    if k.startswith("p|") and "read" in v: RAWPH.setdefault(k.split("|", 1)[1], bool(re.search(r"(?i)product\s*hunt|producthunt", v["read"].get("page_excerpt") or "")))
TE = pd.DataFrame(TE); TE["rank"] = TE.id.map(lambda i: float(byid[i].daily_rank)); PHM = re.compile(r"(?i)product\s*hunt|producthunt")
TE["ph_mention"] = TE.id.map(lambda i: RAWPH.get(i, False)); print("ph_mention share in test", round(float(TE.ph_mention.mean()), 3), flush=True)
print("test", TE.set.value_counts().to_dict(), flush=True)


def make_json(Dtr, serve_src):
    idf, mu, sd, m = fit(Dtr); nV = len(idf); coef = m.coef_
    lb = {"vocab": {t: [idf[t], float(coef[k])] for k, t in enumerate(idf)}, "topics_order": VOCAB, "dense_mean": list(mu), "dense_sd": list(sd),
          "dense_coef": list(coef[nV:nV + len(mu)]), "intercept": float(m.intercept_ + coef[-1] * serve_src)}
    ids = Dtr.id.unique(); oof = []
    for a, b in KFold(5, shuffle=True, random_state=0).split(ids):
        tr, te = Dtr[Dtr.id.isin(ids[a])], Dtr[Dtr.id.isin(ids[b]) & (Dtr.src == serve_src)]
        if len(te): oof.append(te.assign(s=score_model(*fit(tr), te)))
    P = pd.concat(oof); lb["score_percentile_cuts"] = list(np.percentile(P.s, np.arange(1, 100)))
    lb["bands"] = []
    for q in range(10):
        lo, hi = np.percentile(P.s, [q * 10, (q + 1) * 10]); g = P[(P.s >= lo) & ((P.s < hi) if q < 9 else (P.s <= hi))]
        lb["bands"].append({"daily_rank_p10_p50_p90": [float(x) for x in np.percentile(g["rank"], [10, 50, 90])]})
    return lb


ARMS = {"a_ph": (D[TRm & (D.src == 0)], 0, "short"), "b_page": (D[TRm & (D.src == 1)], 1, "long"), "d_both": (D[TRm], 1, "long")}
S = {}
for arm, (Dtr, src, inp) in ARMS.items():
    lb = make_json(Dtr.reset_index(drop=True), src); rows = []
    for r in TE.itertuples():
        desc = r.summary if inp == "short" else r.summary + " " + r.excerpt[:1500]
        s = try_sim._band_score(lb, r.name, r.tagline, desc, r.topics); p = sum(1 for c in lb["score_percentile_cuts"] if c < s)
        b = lb["bands"][min(9, p // 10)]["daily_rank_p10_p50_p90"]; rows.append((p, float(b[0] <= r.rank <= b[2]), b[2] - b[0]))
    S[arm] = np.array(rows); print(arm, "done", flush=True)


def summ(mask):
    rk = TE["rank"].values[mask]; n = int(mask.sum()); out = {"n": n}
    for arm in S:
        out[arm] = {"spearman": round(float(spearmanr(S[arm][mask, 0], -rk).correlation), 3), "coverage": round(float(S[arm][mask, 1].mean()), 3), "width": round(float(S[arm][mask, 2].mean()), 1)}
    for arm in ("b_page", "d_both"):
        bs = []
        for _ in range(2000):
            j = rng.integers(0, n, n); bs.append(spearmanr(S[arm][mask][j, 0], -rk[j]).correlation - spearmanr(S["a_ph"][mask][j, 0], -rk[j]).correlation)
        out[arm]["minus_a (paired)"] = [round(float(x), 3) for x in np.percentile(bs, [2.5, 50, 97.5])]
    return out
res = {"design": __doc__.split("\n    python")[0], "train_launches": int(D[TRm].id.nunique()), "pooled": summ(np.ones(len(TE), bool)),
       "pooled_no_ph_mention": summ(~TE.ph_mention.values)}
for st in ("2026-09", "2026-10", "fresh"): res[f"set {st}"] = summ((TE.set == st).values)
json.dump(res, open(os.path.join(OUT, "band_settle.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1))
