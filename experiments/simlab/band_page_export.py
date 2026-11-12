"""Export the page-trained rank band (model d of band_page.py: page rows + PH-description rows with a source flag) in the plain-JSON
form of launch_band.json, so the site's own try_sim._band_score can score it unchanged. Features replicate _band_score exactly:
text = "name. tagline. description topics" lowercased, tokens [a-z0-9]+, unigrams + bigrams, x = (1 + ln count) * idf, L2-normalised;
dense = topic flags (page-read topic vocabulary) + ln(1+len(description)), ln(1+len(tagline)), number of topics, standardised; the
source flag (page = 1) is folded into the intercept. Page rows: description = summary + " " + page_excerpt[:1500] (what the site
must pass); PH rows: the PH description. Training: the 2,974 held page reads (Jan-Oct 2026) + their PH descriptions. Cuts and rank
bands from 5-fold out-of-fold page-row scores. Validation through try_sim._band_score on the 130 fresh Oct 27 - Nov 10 page reads.
    python band_page_export.py <ph-website worktree> <scratchpad> <band_page out dir>
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
    if "fail" in v or i not in byid or byid[i].day > "2026-10-24": continue
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


# out-of-fold page-row scores (folds by launch) -> cuts and bands
ids = D.id.unique(); oof = pd.Series(np.nan, index=D.index)
for a, b in KFold(5, shuffle=True, random_state=0).split(ids):
    tr, te = D[D.id.isin(ids[a])], D[D.id.isin(ids[b]) & (D.src == 1)]; oof[te.index] = score_model(*fit(tr), te)
P = D[D.src == 1].assign(s=oof[D.src == 1]); cuts = np.percentile(P.s, np.arange(1, 100)).tolist()
bands = []
for q in range(10):
    lo, hi = np.percentile(P.s, [q * 10, (q + 1) * 10]); g = P[(P.s >= lo) & ((P.s < hi) if q < 9 else (P.s <= hi))]
    bands.append({"decile": q, "score_min": round(float(g.s.min()), 4), "score_max": round(float(g.s.max()), 4), "daily_rank_p10_p50_p90": [float(x) for x in np.percentile(g["rank"], [10, 50, 90])],
                  "votes_p10_p50_p90": [float(x) for x in np.percentile(g.votes, [10, 50, 90])], "share_top3": round(float((g["rank"] <= 3).mean()), 3), "share_top10": round(float((g["rank"] <= 10).mean()), 3), "n": int(len(g))})
idf, mu, sd, m = fit(D); nV = len(idf); coef = m.coef_
lb = {"version": "page-band-v1", "trained_on": {"launches": int(D.id.nunique()), "days": [str(min(byid[i].day for i in ids)), str(max(byid[i].day for i in ids))],
      "rows": "held product-site page reads (site extraction + READ_PROMPT, fetched Oct 25 2026, PH-outcome phrases stripped) + the same launches' PH descriptions, source flag folded into the intercept for page input"},
      "recipe": {"input": "page read: name, tagline, description = summary + ' ' + page_excerpt[:1500], topics = page-read topics (score with try_sim._band_score unchanged)",
                 "paste_path": "for pasted launch text use launch_band.json (validated on PH descriptions, Spearman 0.59 on the fresh 130); this file is for page reads"},
      "vocab": {t: [round(idf[t], 5), round(float(coef[k]), 6)] for k, t in enumerate(idf)}, "topics_order": VOCAB,
      "dense_names": [f"topic:{t}" for t in VOCAB] + ["ln_desc_len", "ln_tagline_len", "n_topics"], "dense_mean": [float(x) for x in mu], "dense_sd": [float(x) for x in sd],
      "dense_coef": [float(x) for x in coef[nV:nV + len(mu)]], "intercept": float(m.intercept_ + coef[-1] * 1.0), "score_percentile_cuts": [round(float(c), 5) for c in cuts], "bands": bands}
# validation on the 130 fresh page reads via the site's own scorer
FK = json.load(open(os.path.join(SP, "try_fixes/cache.json"))); out = []
for k, v in FK.items():
    if not k.startswith("p|") or "read" not in v: continue
    i = k.split("|", 1)[1]; rd = v["read"]
    if i not in byid: continue
    desc = (rd.get("summary") or "") + " " + LEAK.sub(" ", rd.get("page_excerpt") or "")[:1500]
    s = try_sim._band_score(lb, rd.get("name") or "", rd.get("tagline") or "", desc, rd.get("topics") or []); pct = sum(1 for c in lb["score_percentile_cuts"] if c < s)
    b = lb["bands"][min(9, pct // 10)]["daily_rank_p10_p50_p90"]
    s0 = try_sim._band_score(LB0, rd.get("name") or "", rd.get("tagline") or "", rd.get("summary") or "", rd.get("topics") or []); p0 = sum(1 for c in LB0["score_percentile_cuts"] if c < s0)
    b0 = LB0["bands"][min(9, p0 // 10)]["daily_rank_p10_p50_p90"]; rk = float(byid[i].daily_rank)
    out.append((pct, p0, rk, float(b[0] <= rk <= b[2]), float(b0[0] <= rk <= b0[2]), b[2] - b[0], b0[2] - b0[0]))
A = np.array(out); n = len(A); bs = []
for _ in range(2000):
    j = rng.integers(0, n, n); bs.append(spearmanr(A[j, 0], -A[j, 2]).correlation - spearmanr(A[j, 1], -A[j, 2]).correlation)
val = {"n": n, "page_band_v1_spearman": round(float(spearmanr(A[:, 0], -A[:, 2]).correlation), 3), "site_now_spearman (launch_band.json on name/tagline/summary)": round(float(spearmanr(A[:, 1], -A[:, 2]).correlation), 3),
       "difference (paired bootstrap)": [round(float(x), 3) for x in np.percentile(bs, [2.5, 50, 97.5])], "page_band_v1_coverage": round(float(A[:, 3].mean()), 3), "site_now_coverage": round(float(A[:, 4].mean()), 3),
       "page_band_v1_mean_width": round(float(A[:, 5].mean()), 1), "site_now_mean_width": round(float(A[:, 6].mean()), 1),
       "note": "launch_band.json was trained on launches through Nov 10 (incl. these 130), so the site-now figure is partly in-sample; page_band_v1 never saw them"}
lb["heldout_accuracy"] = {"fresh_page_reads_oct27_nov10": val}
lb["caveat"] = "Training pages were fetched months after launch (PH-outcome phrases stripped). Validated on 130 page reads fetched fresh through the site's code."
json.dump(lb, open(os.path.join(BP, "launch_band_page_v1.json"), "w")); print(json.dumps(val, indent=1)); print("bytes", os.path.getsize(os.path.join(BP, "launch_band_page_v1.json")))
