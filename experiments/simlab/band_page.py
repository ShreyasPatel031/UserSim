"""Train the rank band on what the site reads (orchestrator 10:45Z Nov 12). The site's band (launch_band.json, a ridge on PH launch
descriptions) is served product-site text and its link with final rank falls from 0.59 to 0.31.
Training data: held product-site HTML for past launches (fame/sites.jsonl 'live' pages, fetched Oct 25 2026, i.e. months after
launch) -> the SAME extraction the site uses (mvp/ph_site/safe_fetch.extract) -> PH-outcome phrases stripped (features.LEAK_WORDS
rule: "product hunt", "product of the day/week/month", "#1 product", "upvote"; launches whose raw page mentions Product Hunt are
flagged) -> the site's READ_PROMPT page read (gemini-2.5-flash-lite), which gives name / tagline / summary / topics / pricing /
clarity / strengths / doubts. Pricing sub-page not fetched (held pages only).
Models (target ln(1+votes); month-forward on old launches; trained on all held launches for the fresh test):
  (a) CURRENT  launch_band.json scored on the site's band input (name, tagline, summary + page_excerpt[:600], topics)
  (b) TFIDF    word 1-2 gram TF-IDF ridge on page text "name. tagline. summary. excerpt[:1500]"
  (b2) EMB     ridge on gemini-embedding-001 (256-d) of the same text
  (c) STRUCT   (b) + page-read topics (one-hot) and text length (pricing / clarity not held for the fresh reads)
  (d) BOTH     (c) trained on page rows AND PH-description rows (same features, PH text in place of page text) + a source flag;
               scored as source = page
Band: deciles of the model's 5-fold out-of-fold training scores; 10th-90th percentile of final daily rank per decile from those rows.
Fresh test: the 130 Oct 27 - Nov 10 launches fetched and read through the site's code (try_fixes cache); none in training.
Metrics: Spearman of the band percentile with -rank (pooled; launch bootstrap), band coverage / mean width, paired vs (a); old
launches month-forward also within-day Spearman and daily top 3/5/10 on days with >= 10 page rows; with / without PH-mention pages.
Paste path: the PH description is the proxy for visitor-pasted text (0.59 on the same 130 in try_fixes).
    python band_page.py <ph-website worktree> <scratchpad> <out dir>
"""
import asyncio, glob, json, os, re, sys, time
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge

WT, SP, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
os.environ["TRY_SIGNING_KEY"] = "local-dummy-key-for-offline-eval-0123456789"; os.environ["TRY_LOCAL_LIMITS"] = "1"
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(SP, "gcp_key.json")); os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox")
sys.path[:0] = [WT, os.path.join(WT, "src")]
from mvp.ph_site import try_sim, safe_fetch, gcs  # noqa: E402
from capability import gemini_config as GC  # noqa: E402
LEAK = re.compile(r"(?i)product\s*hunt|product of the (day|week|month)|#\s*1\s*product|upvote"); PHM = re.compile(r"(?i)product\s*hunt|producthunt")
VOCAB = try_sim.index()["meta"]["vocab"]; LB = gcs.read_json("results/web/launch_band.json"); USE = {"in": 0, "out": 0}
cache_f = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f)) if os.path.exists(cache_f) else {}

L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna()].copy(); L["id"] = L.id.astype(str); L["y"] = np.log1p(pd.to_numeric(L.votes).astype(float)); L["rank"] = L.daily_rank.astype(float)
L["mon"] = L.day.str[:7]; byid = {r.id: r for r in L.itertuples()}
pages = {}
for l in open(os.path.join(SP, "fame/sites.jsonl")):
    x = json.loads(l)
    if x.get("src") == "live" and x.get("html") and str(x["id"]) in byid and byid[str(x["id"])].day <= "2026-10-24":
        ex = safe_fetch.extract(x["html"]); pages[str(x["id"])] = {"title": ex["title"], "description": ex["description"], "text": ex["text"], "ph_mention": bool(PHM.search(x["html"]))}
print("held pages", len(pages), flush=True)


async def read(i, p, sem):
    async with sem:
        if i in K: return
        txt = LEAK.sub(" ", p["text"]); desc = LEAK.sub(" ", p["description"] or "")
        if len(txt.strip()) < 80: K[i] = {"fail": "no text"}; return
        prompt = try_sim.READ_PROMPT.format(url="(held page)", title=LEAK.sub(" ", p["title"] or ""), desc=desc, text=txt[:9000], pricing="", vocab=", ".join(VOCAB))
        try:
            raw = await GC.gemini_chat([{"role": "user", "content": prompt}], model=try_sim.MODEL, temperature=0.2, max_retries=3, max_output_tokens=1500)
            USE["in"] += len(prompt); USE["out"] += len(raw or ""); a = GC.extract_json(raw)
            if a.get("problem"): K[i] = {"fail": "judge: " + str(a["problem"])[:80]}; return
            a["topics"] = [t for t in (a.get("topics") or []) if t in VOCAB][:4] or ["Productivity"]
            K[i] = {k: a.get(k) for k in ("name", "tagline", "summary", "topics", "audience", "pricing", "strengths", "doubts", "clarity")} | {"page_excerpt": (desc + "\n" + txt)[:2500]}
        except Exception as e:  # noqa: BLE001
            K[i] = {"fail": f"{type(e).__name__}"}


async def main():
    sem = asyncio.Semaphore(12); ids = list(pages)
    for k in range(0, len(ids), 300):
        await asyncio.gather(*[read(i, pages[i], sem) for i in ids[k:k + 300]]); json.dump(K, open(cache_f, "w")); print("read", k + 300, flush=True)
asyncio.run(main())
TR = pd.DataFrame([{"id": i, **K[i]} for i in pages if i in K and "fail" not in K[i]]); TR["ph_mention"] = TR.id.map(lambda i: pages[i]["ph_mention"])
TR = TR.merge(L[["id", "day", "mon", "y", "rank", "name", "tagline", "description", "topics"]].rename(columns={"name": "ph_name", "tagline": "ph_tagline", "description": "ph_desc", "topics": "ph_topics"}), on="id")
print("training page reads", len(TR), "by month", TR.mon.value_counts().sort_index().to_dict(), "ph_mention share", round(float(TR.ph_mention.mean()), 3), flush=True)
FK = json.load(open(os.path.join(SP, "try_fixes/cache.json")))
TE = pd.DataFrame([{"id": k.split("|", 1)[1], **v["read"]} for k, v in FK.items() if k.startswith("p|") and "read" in v])
TE = TE.merge(L[["id", "day", "mon", "y", "rank", "name", "tagline", "description", "topics"]].rename(columns={"name": "ph_name", "tagline": "ph_tagline", "description": "ph_desc", "topics": "ph_topics"}), on="id")
TE["ph_mention"] = TE.page_excerpt.fillna("").str.contains(PHM); TE["page_excerpt"] = TE.page_excerpt.fillna("").map(lambda t: LEAK.sub(" ", t))
print("fresh test", len(TE), flush=True)
phtop = lambda s: [t for t in (json.loads(s) if isinstance(s, str) and s.startswith("[") else []) if t in VOCAB][:4] or ["Productivity"]


def page_text(D): return (D.name.fillna("") + ". " + D.tagline.fillna("") + ". " + D.summary.fillna("") + ". " + D.page_excerpt.fillna("").str[:1500]).tolist()
def ph_text(D): return (D.ph_name.fillna("") + ". " + D.ph_tagline.fillna("") + ". " + D.ph_desc.fillna("")).tolist()
PRC = ["free", "freemium", "paid", "unknown"]


def struct(D, src_ph=False):
    tps = D.ph_topics.map(phtop) if src_ph else D.topics.map(lambda t: t if isinstance(t, list) else [])
    X = np.array([[float(v in t) for v in VOCAB] for t in tps], np.float32)
    # pricing / clarity / strengths / doubts are not held for the 130 fresh reads (try_fixes stored name, tagline, summary,
    # topics, excerpt), so the structured block is topics + text length only, identical for training and test
    txt = ph_text(D) if src_ph else page_text(D); ln = np.array([[np.log1p(len(t))] for t in txt], np.float32)
    return np.hstack([X, ln / 8])


def current(D): return np.array([try_sim._band_score(LB, n or "", t or "", (s or "") + " " + (e or "")[:600], tp if isinstance(tp, list) else []) for n, t, s, e, tp in zip(D.name, D.tagline, D.summary, D.page_excerpt, D.topics)])


EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
import subprocess, urllib.request  # noqa: E402
_tk = {"t": "", "at": 0}
def _token():
    if time.time() - _tk["at"] > 300: _tk["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tk["at"] = time.time()
    return _tk["t"]
def embed(texts, tag):
    f = os.path.join(OUT, f"emb_{tag}.npy")
    if os.path.exists(f) and len(np.load(f)) == len(texts): return np.load(f)
    out = []
    for i in range(0, len(texts), 200):
        for a in range(6):
            try:
                req = urllib.request.Request(EMB, json.dumps({"instances": [{"content": t[:2000], "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]], "parameters": {"outputDimensionality": 256}}).encode(), {"Authorization": "Bearer " + _token(), "Content-Type": "application/json"})
                j = json.load(urllib.request.urlopen(req, timeout=120)); break
            except Exception: time.sleep(3 * (a + 1))  # noqa: BLE001
        out.append(np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32))
    E = np.vstack(out); E /= np.linalg.norm(E, axis=1, keepdims=True) + 1e-9; np.save(f, E); return E


E_tr, E_te = embed(page_text(TR), "train_page"), embed(page_text(TE), "test_page")


def fit_predict(kind, trD, teD, Etr=None, Ete=None):
    """returns test scores and training scores (in-sample, for band cuts)"""
    if kind == "b2":
        m = Ridge(alpha=3.0).fit(Etr, trD.y); return m.predict(Ete), m.predict(Etr)
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=60000, sublinear_tf=True)
    if kind == "d":
        txt = page_text(trD) + ph_text(trD); Xt = vec.fit_transform(txt)
        S = np.vstack([struct(trD), struct(trD, True)]); src = np.r_[np.ones(len(trD)), np.zeros(len(trD))][:, None]
        X = sparse.hstack([Xt, sparse.csr_matrix(np.hstack([S, src]))]).tocsr(); y = np.r_[trD.y.values, trD.y.values]
        m = Ridge(alpha=3.0).fit(X, y)
        Xte = sparse.hstack([vec.transform(page_text(teD)), sparse.csr_matrix(np.hstack([struct(teD), np.ones((len(teD), 1))]))]).tocsr()
        return m.predict(Xte), m.predict(X[: len(trD)])
    Xt = vec.fit_transform(page_text(trD)); Xte = vec.transform(page_text(teD))
    if kind == "c": Xt = sparse.hstack([Xt, sparse.csr_matrix(struct(trD))]).tocsr(); Xte = sparse.hstack([Xte, sparse.csr_matrix(struct(teD))]).tocsr()
    m = Ridge(alpha=3.0).fit(Xt, trD.y); return m.predict(Xte), m.predict(Xt)


from sklearn.model_selection import KFold  # noqa: E402


def oof_scores(kind, trD, Etr=None):
    """5-fold out-of-fold training scores: band cuts / rank bands must come from held-out scores (in-sample ridge scores on
    TF-IDF are overfit, which made the bands too narrow)"""
    o = np.zeros(len(trD))
    for a, b in KFold(5, shuffle=True, random_state=0).split(trD):
        o[b] = fit_predict(kind, trD.iloc[a], trD.iloc[b], None if Etr is None else Etr[a], None if Etr is None else Etr[b])[0]
    return o


def band_eval(score_te, score_tr, trD, teD):
    cuts = np.percentile(score_tr, np.arange(10, 100, 10)); dtr, dte = np.searchsorted(cuts, score_tr), np.searchsorted(cuts, score_te)
    lo = {q: np.percentile(trD["rank"].values[dtr == q], 10) for q in range(10)}; hi = {q: np.percentile(trD["rank"].values[dtr == q], 90) for q in range(10)}
    pct = np.array([np.mean(score_tr < s) * 100 for s in score_te]); cov = np.array([lo[q] <= r <= hi[q] for q, r in zip(dte, teD["rank"])], float)
    return pct, cov, np.array([hi[q] - lo[q] for q in dte])


def lb_band(score_te):                      # launch_band.json's own cuts / bands
    pct = np.array([sum(1 for c in LB["score_percentile_cuts"] if c < s) for s in score_te], float)
    cov, w = [], []
    for p, r in zip(pct, TE["rank"] if len(score_te) == len(TE) else []):
        b = LB["bands"][min(9, int(p) // 10)]["daily_rank_p10_p50_p90"]; cov.append(float(b[0] <= r <= b[2])); w.append(b[2] - b[0])
    return pct, np.array(cov), np.array(w)


def sp_ci(pct, rank, B=2000, other=None):
    n = len(pct); s0 = spearmanr(pct, -rank).correlation; bs, dd = [], []
    for _ in range(B):
        i = rng.integers(0, n, n); bs.append(spearmanr(pct[i], -rank[i]).correlation)
        if other is not None: dd.append(bs[-1] - spearmanr(other[i], -rank[i]).correlation)
    out = {"spearman": round(float(s0), 3), "ci": [round(float(x), 3) for x in np.percentile(bs, [2.5, 97.5])], "n": int(n)}
    if other is not None: out["minus_a (paired)"] = [round(float(x), 3) for x in np.percentile(dd, [2.5, 50, 97.5])]
    return out


res = {"design": __doc__.split("\n    python")[0], "held_pages": len(pages), "training_page_reads": int(len(TR)), "training_by_month": TR.mon.value_counts().sort_index().to_dict(),
       "training_ph_mention_share": round(float(TR.ph_mention.mean()), 3), "fresh_test": int(len(TE)), "fresh": {}, "fresh_no_ph_mention": {}, "old_month_forward": {}}
for sub, mask_tr, mask_te in (("fresh", np.ones(len(TR), bool), np.ones(len(TE), bool)), ("fresh_no_ph_mention", ~TR.ph_mention.values, ~TE.ph_mention.values)):
    trD, teD = TR[mask_tr], TE[mask_te]; rk = teD["rank"].values
    pa, ca, wa = lb_band(current(teD)) if sub == "fresh" else (None, None, None)
    if sub != "fresh":
        pa = np.array([sum(1 for c in LB["score_percentile_cuts"] if c < s) for s in current(teD)], float)
        ca = np.array([float(LB["bands"][min(9, int(p) // 10)]["daily_rank_p10_p50_p90"][0] <= r <= LB["bands"][min(9, int(p) // 10)]["daily_rank_p10_p50_p90"][2]) for p, r in zip(pa, rk)]); wa = np.zeros(len(pa))
    out = {"a_current": sp_ci(pa, rk) | {"coverage": round(float(ca.mean()), 3)}}
    for kind in ("b", "b2", "c", "d"):
        st, _ = fit_predict(kind, trD, teD, E_tr[mask_tr], E_te[mask_te]); sr = oof_scores(kind, trD, E_tr[mask_tr]); p, cv, w = band_eval(st, sr, trD, teD)
        out[kind] = sp_ci(p, rk, other=pa) | {"coverage": round(float(cv.mean()), 3), "mean_width": round(float(w.mean()), 1)}
    res[sub] = out; print(sub, json.dumps(out), flush=True)
# month-forward on old launches
mons = sorted(TR.mon.unique()); P = {k: pd.Series(np.nan, index=TR.index) for k in ("a", "b", "c", "d")}
for m in mons[2:]:
    tr, te = TR[TR.mon < m], TR[TR.mon == m]
    if len(te) < 30: continue
    P["a"][te.index] = current(te)
    for kind in ("b", "c", "d"): P[kind][te.index] = fit_predict(kind, tr, te)[0]
T = TR.assign(**{f"s_{k}": v for k, v in P.items()}); T = T[T.s_a.notna()]
res["note_old"] = "launch_band.json (a) was trained on launches that include these months, so (a) is partly in-sample on the old set"
for k in ("a", "b", "c", "d"):
    wd = [spearmanr(g[f"s_{k}"], -g["rank"]).correlation for d, g in T.groupby("day") if len(g) >= 10]
    tk = {kk: np.mean([len(set(g.nlargest(kk, f"s_{k}").id) & set(g.nsmallest(kk, "rank").id)) / kk for d, g in T.groupby("day") if len(g) >= 10]) * 100 for kk in (3, 5, 10)}
    res["old_month_forward"][k] = {"pooled_spearman": round(float(spearmanr(T[f"s_{k}"], -T["rank"]).correlation), 3), "within_day_spearman": round(float(np.nanmean(wd)), 3), "days": len(wd),
                                   "top3_5_10_among_page_launches": [round(float(v), 1) for v in tk.values()], "launches": int(len(T))}
res["gemini_usd_estimate"] = round(USE["in"] / 4 / 1e6 * 0.10 + USE["out"] / 4 / 1e6 * 0.40, 3)
json.dump(res, open(os.path.join(OUT, "band_page.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
