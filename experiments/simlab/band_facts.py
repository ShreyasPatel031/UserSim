"""Page band v2 test (orchestrator 08:47Z Nov 12): the orchestrator's LLM-free stack (page facts + outcome retrieval + topic prior,
gs://.../tmp/orchestrator/band/{prep,run}.py) on top of E5's d_both page band WITH the LLM read.
Train: page reads of launches <= 2026-08-31 (band_page cache). Test: held Sep 1 - Oct 24 page reads + the 130 fresh Oct 27 - Nov 10
reads (try_fixes cache) = the band_settle 856.
  B0     d_both (page + PH rows, source flag) scored on the read (name / tagline / summary + excerpt[:1500], read topics);
         training scores 5-fold out-of-fold (as in launch_band_page_v1)
  facts  37 regex / count features exactly as prep.py: text facts on the page excerpt (leak-stripped), HTML facts on the raw page
         (held: fame/sites.jsonl live fetch Oct 25; fresh: raw page re-fetched Nov 12 from the same URL; missing -> training mean)
  retr30 TF-IDF retrieval (the band's own tokenizer, 20k uni+bigrams, fit on <= Aug 31) of the 30 nearest earlier launches' PH text,
         their rank-percentile / ln votes (run 1 used sklearn TfidfVectorizer: reports/band_v2/band_facts_sklearn_retr.json)
  topic  shrunk base rate of rank-percentile for the read's topics, months strictly before
Stack: ridge on standardised [B0, blocks], alpha by month-forward Apr..Aug on training only.
PRIMARY (pre-registered by the orchestrator): S = B0 + facts + retr30 + topic, pooled Spearman with -rank on the 856, paired launch
bootstrap vs B0; export only if > 0 on the 856 AND the same sign on the fresh 130. Also without testimonial / logo words.
    python band_facts.py <scratchpad> <launch_band_page_v1.json> <out dir>
"""
import glob, json, math, os, re, sys
from collections import Counter
import numpy as np, pandas as pd
from scipy import sparse
from scipy.stats import spearmanr
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

SP, V1, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); CUT = "2026-08-31"
LB1 = json.load(open(V1)); VOCAB = LB1["topics_order"]
LEAK = re.compile(r"(?i)product\s*hunt|product of the (day|week|month)|#\s*1\s*product|upvote"); PHM = re.compile(r"(?i)product\s*hunt|producthunt")
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna()].copy(); L["id"] = L.id.astype(str); L["rank"] = L.daily_rank.astype(float); L["y"] = np.log1p(L.votes.astype(float))
L["nday"] = L.groupby("day").id.transform("count"); L["rp"] = 1 - (L["rank"] - 0.5) / L.nday.clip(lower=L["rank"])
phtop = lambda s: [t for t in (json.loads(s) if isinstance(s, str) and s.startswith("[") else []) if t in VOCAB][:4] or ["Productivity"]
L["ptop"] = L.topics.map(phtop); L["phtext"] = L.name.fillna("") + ". " + L.tagline.fillna("") + ". " + L.description.fillna("")
L = L.sort_values(["day", "id"]).reset_index(drop=True); byid = {r.id: r for r in L.itertuples()}

# ---------- reads ----------
K = json.load(open(os.path.join(SP, "band_page/cache.json"))); FK = json.load(open(os.path.join(SP, "try_fixes/cache.json")))
R = []
for i, v in K.items():
    if "fail" in v or i not in byid or byid[i].day > "2026-10-24": continue
    R.append({"id": i, "set": "train" if byid[i].day <= CUT else byid[i].day[:7], "name": v.get("name") or "", "tagline": v.get("tagline") or "", "summary": v.get("summary") or "",
              "excerpt": v.get("page_excerpt") or "", "topics": [t for t in (v.get("topics") or []) if t in VOCAB][:4] or ["Productivity"]})
for k, v in FK.items():
    if not k.startswith("p|") or "read" not in v: continue
    i = k.split("|", 1)[1]; rd = v["read"]
    if i not in byid: continue
    R.append({"id": i, "set": "fresh", "name": rd.get("name") or "", "tagline": rd.get("tagline") or "", "summary": rd.get("summary") or "",
              "excerpt": LEAK.sub(" ", rd.get("page_excerpt") or ""), "topics": [t for t in (rd.get("topics") or []) if t in VOCAB][:4] or ["Productivity"]})
D = pd.DataFrame(R).drop_duplicates("id", keep="last")
for c in ("day", "rank", "y", "rp", "ptop"): D[c] = D.id.map(lambda i: getattr(byid[i], c))
D["desc_long"] = D.summary + " " + D.excerpt.str[:1500]
D = D.sort_values(["day", "id"]).reset_index(drop=True); print(D.set.value_counts().to_dict(), flush=True)

# ---------- raw html facts (prep.py definitions) ----------
HTML = {}
for l in open(os.path.join(SP, "fame/sites.jsonl")):
    if '"live"' not in l[:200]: continue
    x = json.loads(l)
    if x.get("src") == "live" and x.get("html"): HTML[str(x["id"])] = x["html"]
FRESH_HTML = {}
for l in open(os.path.join(SP, "band_v2/fresh_html.jsonl")):
    x = json.loads(l)
    if x.get("html"): FRESH_HTML[x["id"]] = x["html"]
W = lambda p: re.compile(p, re.I)
TW = {"w_pricing": W(r"\bpricing\b|\bplans?\b|/mo\b|per month|\$\d"), "w_free": W(r"\bfree\b"), "w_trial": W(r"free trial|\btrial\b"),
      "w_opensource": W(r"open[- ]source|\bMIT license|apache 2"), "w_api": W(r"\bAPI\b|\bSDK\b"), "w_docs": W(r"\bdocs\b|documentation"),
      "w_login": W(r"\blog ?in\b|\bsign ?in\b"), "w_signup": W(r"sign ?up|get started|start for free"), "w_demo": W(r"book a demo|request a demo|schedule a demo|talk to sales|contact sales"),
      "w_enterprise": W(r"\benterprise\b|\bSOC ?2\b|\bSSO\b|\bGDPR\b"), "w_testimonial": W(r"testimonial|what (our )?(customers|users) say|loved by|trusted by|used by"),
      "w_logos": W(r"trusted by|backed by|as seen (on|in)|featured (in|on)"), "w_ai": W(r"\bAI\b|artificial intelligence"), "w_agent": W(r"\bagents?\b|agentic"),
      "w_llm": W(r"\bLLMs?\b|\bGPT|\bClaude\b|\bGemini\b|\bMCP\b"), "w_b2b": W(r"\bteams?\b|\bbusiness(es)?\b|\bB2B\b|\bcompan(y|ies)\b|\bworkflows?\b|\bcustomers\b|\bROI\b"),
      "w_consumer": W(r"\byour life\b|\bfamily\b|\bfriends\b|\bfun\b|\bhabits?\b|\bpersonal\b"), "w_waitlist": W(r"waitlist|wait list|coming soon|early access"),
      "w_download": W(r"\bdownload\b"), "w_mac": W(r"\bmacOS\b|\bMac\b"), "w_chrome": W(r"chrome extension|add to chrome"), "w_yc": W(r"Y ?Combinator|\bYC\b")}
def facts(text, h):
    t = LEAK.sub(" ", text or ""); words = re.findall(r"[A-Za-z']+", t); nw = max(len(words), 1)
    we = sum(w.lower() in ("we", "our", "us", "we're", "we've") for w in words); ii = sum(w in ("I", "I'm", "I've", "my") for w in words)
    d = {"f_len": np.log1p(len(t)), "f_words": np.log1p(nw), "f_we": we / nw * 100, "f_i": ii / nw * 100, "f_nonascii": sum(ord(c) > 127 for c in t[:3000]) / max(len(t[:3000]), 1)}
    if h:
        hl = h.lower(); lang = (re.search(r'<html[^>]*\blang=["\']?([a-zA-Z]{2})', h) or [None, ""])[1].lower()
        d |= {"f_h1": len(re.findall(r"<h1\b", hl)), "f_h2": len(re.findall(r"<h[23]\b", hl)), "f_links": np.log1p(len(re.findall(r'href=["\']([^"\'#]+)["\']', h, re.I)[:400])),
              "f_appstore": int("apps.apple.com" in hl or "itunes.apple.com" in hl), "f_play": int("play.google.com" in hl), "f_github": int("github.com/" in hl),
              "f_social": sum(int(s in hl) for s in ("twitter.com/", "x.com/", "linkedin.com/", "discord.gg", "discord.com/invite", "youtube.com/", "instagram.com/", "tiktok.com/", "reddit.com/")),
              "f_lang_en": int(lang in ("", "en")), "f_img": np.log1p(hl.count("<img")), "f_form": int("<form" in hl)}
    for k, r in TW.items(): d[k] = int(bool(r.search(t)))
    return d
FR = []
for r in D.itertuples():
    h = FRESH_HTML.get(r.id) if r.set == "fresh" else HTML.get(r.id)
    FR.append(facts(r.excerpt, h) | {"has_html": float(h is not None), "ph_mention": bool(PHM.search(h)) if h else bool(PHM.search(r.excerpt))})
F = pd.DataFrame(FR); D = pd.concat([D, F], axis=1)
FCOLS = [c for c in F.columns if c.startswith("f_") or c.startswith("w_")]; TESTI = ["w_testimonial", "w_logos"]
print("has_html by set", D.groupby("set").has_html.mean().round(3).to_dict(), "facts", len(FCOLS), flush=True)

# ---------- B0: d_both (band_settle make_json recipe), OOF on train page rows ----------
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
    else:
        Rx = pd.DataFrame({"name": [byid[i].name or "" for i in Dx.id], "tagline": [byid[i].tagline or "" for i in Dx.id], "desc": [byid[i].description or "" for i in Dx.id], "topics": Dx.ptop.values})
    Rx["src"] = float(src); Rx["y"] = Dx.y.values; Rx["terms"] = [terms(*x) for x in zip(Rx.name, Rx.tagline, Rx.desc, Rx.topics)]; return Rx
def fit(Rx):
    idf = build_vocab(Rx.terms.tolist()); De = dense(Rx); mu, sd = De.mean(0), De.std(0) + 1e-9
    X = sparse.hstack([tfidf(Rx.terms.tolist(), idf), sparse.csr_matrix((De - mu) / sd), sparse.csr_matrix(Rx[["src"]].values)]).tocsr(); return idf, mu, sd, Ridge(alpha=3.0).fit(X, Rx.y.values)
def score(M, Rx):
    idf, mu, sd, m = M; return m.predict(sparse.hstack([tfidf(Rx.terms.tolist(), idf), sparse.csr_matrix((dense(Rx) - mu) / sd), sparse.csr_matrix(Rx[["src"]].values)]).tocsr())
TRi, TEi = np.where(D.set == "train")[0], np.where(D.set != "train")[0]; DT, DE = D.iloc[TRi].reset_index(drop=True), D.iloc[TEi].reset_index(drop=True)
both = lambda Dx: pd.concat([rows(Dx, 1), rows(Dx, 0)], ignore_index=True)
b0_te = score(fit(both(DT)), rows(DE, 1)); b0_oof = np.zeros(len(DT))
for a, b in KFold(5, shuffle=True, random_state=0).split(DT): b0_oof[b] = score(fit(both(DT.iloc[a])), rows(DT.iloc[b], 1))
print("B0 test spearman", round(spearmanr(b0_te, -DE["rank"]).correlation, 3), flush=True)

# ---------- retrieval and topic prior ----------
# retrieval in the band's own pure-python TF-IDF (servable on the site without sklearn): PH text of launches, vocab fit on PH text
# of launches <= CUT (EXPORT: all), unigrams + bigrams, 20,000 terms, min_df 3; cosine; pool = launches strictly earlier than the query day
EXPORT = os.environ.get("EXPORT") == "1"
ph_terms = [terms(n or "", t or "", d or "", []) for n, t, d in zip(L.name, L.tagline, L.description)]
RIDF = build_vocab([ts for ts, d in zip(ph_terms, L.day) if EXPORT or d <= CUT], max_terms=20000)
Xpool = tfidf(ph_terms, RIDF); pday = L.day.values; prp = L.rp.values; py = L.y.values
Q = tfidf([terms(n, t, d, []) for n, t, d in zip(D.name, D.tagline, D.desc_long)], RIDF); Sm = (Q @ Xpool.T).toarray().astype(np.float32); RR = []
for r in range(len(D)):
    s = np.where(pday < D.day.iat[r], Sm[r], -1.0); o = np.argsort(-s)[:30]; o = o[s[o] > -1]; w = np.clip(s[o], 1e-4, None)
    RR.append([prp[o].mean(), (w * prp[o]).sum() / w.sum(), (w * py[o]).sum() / w.sum(), s[o].mean(), s[o[0]]] if len(o) else [np.nan] * 5)
RR = np.array(RR, float)
g_all = {}
for mon in sorted(D.day.str[:7].unique()):
    E = L[L.day < mon + "-01"]; gm = E.rp.mean(); c, s_ = Counter(), Counter()
    for tp, r in zip(E.ptop, E.rp):
        for t in tp: c[t] += 1; s_[t] += r
    g_all[mon] = (gm, {t: (s_[t] + 20 * gm) / (c[t] + 20) for t in c})
D["topic_prior"] = [np.mean([g_all[d[:7]][1].get(t, g_all[d[:7]][0]) for t in tp]) for d, tp in zip(D.day, D.topics)]
def blk(nm, idx):
    if nm == "retr30": return RR[idx]
    if nm == "facts": return D.iloc[idx][FCOLS].values.astype(float)
    if nm == "facts_noT": return D.iloc[idx][[c for c in FCOLS if c not in TESTI]].values.astype(float)
    if nm == "topic": return D.iloc[idx][["topic_prior"]].values
def alpha_mf(X, y, days):
    best = None
    for al in (0.3, 1, 3, 10, 30, 100, 300, 1000):
        rs = []
        for m in ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08"):
            a, b = (days < m + "-01").values, (days.str[:7] == m).values
            if a.sum() < 100 or b.sum() < 20: continue
            mu, sd = np.nanmean(X[a], 0), np.nanstd(X[a], 0) + 1e-9; f = lambda Z: np.nan_to_num((Z - mu) / sd)
            rs.append(spearmanr(Ridge(alpha=al).fit(f(X[a]), y[a]).predict(f(X[b])), y[b]).correlation)
        if best is None or np.mean(rs) > best[1]: best = (al, np.mean(rs))
    return best[0]
INFO = {}
def stack(names, use_b0=True):
    Xtr = np.hstack([blk(n, TRi) for n in names] + ([b0_oof[:, None]] if use_b0 else [])); Xte = np.hstack([blk(n, TEi) for n in names] + ([b0_te[:, None]] if use_b0 else []))
    y = DT.y.values; mu, sd = np.nanmean(Xtr, 0), np.nanstd(Xtr, 0) + 1e-9; f = lambda Z: np.nan_to_num((Z - mu) / sd); al = alpha_mf(Xtr, y, DT.day)
    m = Ridge(alpha=al).fit(f(Xtr), y); oof = np.zeros(len(y))
    for a, b in KFold(5, shuffle=True, random_state=0).split(Xtr): oof[b] = Ridge(alpha=al).fit(f(Xtr[a]), y[a]).predict(f(Xtr[b]))
    return oof, m.predict(f(Xte)), {"alpha": al, "coef": np.round(m.coef_, 4).tolist(), "intercept": float(m.intercept_), "mu": mu.tolist(), "sd": sd.tolist()}
def band(oof, te):
    cuts = np.percentile(oof, np.arange(1, 100)); p = np.searchsorted(cuts, te, side="left"); Bs = []
    for q in range(10):
        lo, hi = np.percentile(oof, [q * 10, (q + 1) * 10]); g = (oof >= lo) & ((oof < hi) if q < 9 else (oof <= hi)); Bs.append(np.percentile(DT["rank"].values[g], [10, 90]))
    lohi = np.array([Bs[min(9, x // 10)] for x in p]); rk = DE["rank"].values
    return p.astype(float), ((lohi[:, 0] <= rk) & (rk <= lohi[:, 1])).astype(float), lohi[:, 1] - lohi[:, 0]
ARMS = {"B0": band(b0_oof, b0_te)}
VAR = {"S_PRIMARY": (["facts", "retr30", "topic"], True), "S_no_testimonial": (["facts_noT", "retr30", "topic"], True),
       "B0+facts": (["facts"], True), "B0+facts_noT": (["facts_noT"], True), "B0+retr30": (["retr30"], True), "B0+topic": (["topic"], True),
       "B0+facts+topic": (["facts", "topic"], True), "B0+facts_noT+topic": (["facts_noT", "topic"], True),
       "facts_alone": (["facts"], False), "topic_alone": (["topic"], False), "retr30_alone": (["retr30"], False)}
for v, (nm, ub) in VAR.items():
    oof, te, INFO[v] = stack(nm, ub); ARMS[v] = band(oof, te); print(v, round(spearmanr(te, -DE["rank"]).correlation, 3), flush=True)
rk = DE["rank"].values
def summ(m):
    n = int(m.sum()); idx = np.where(m)[0]; o = {"n": n}; Bt = [idx[rng.integers(0, n, n)] for _ in range(2000)]
    for a, (p, cov, w) in ARMS.items():
        o[a] = {"spearman": round(float(spearmanr(p[m], -rk[m]).correlation), 3), "coverage": round(float(cov[m].mean()), 3), "width": round(float(w[m].mean()), 1)}
        if a != "B0":
            ds = [spearmanr(p[j], -rk[j]).correlation - spearmanr(ARMS["B0"][0][j], -rk[j]).correlation for j in Bt]
            o[a]["minus_B0 [2.5,50,97.5]"] = [round(float(x), 3) for x in np.percentile(ds, [2.5, 50, 97.5])]
    return o
held = (DE.set != "fresh").values
res = {"design": __doc__.split("\n    python")[0], "train": len(DT), "pooled_856": summ(np.ones(len(DE), bool)), "held_sep_oct": summ(held), "fresh_130": summ(~held),
       "pooled_no_ph_mention": summ(~DE.ph_mention.values.astype(bool)), "has_html_test": round(float(DE.has_html.mean()), 3), "stack_info": INFO, "facts": FCOLS,
       "facts_train_spearman_vs_y": {c: round(float(spearmanr(DT[c].astype(float), DT.y).correlation), 3) for c in FCOLS if DT[c].std() > 0},
       "testimonial_rate": {s: round(float(D[D.set == s][TESTI].max(axis=1).mean()), 3) for s in D.set.unique()}}
json.dump(res, open(os.path.join(OUT, "band_facts.json"), "w"), indent=1, default=float)
pd.DataFrame({"id": DE.id, "set": DE.set, "rank": rk, **{a: ARMS[a][0] for a in ARMS}}).to_parquet(os.path.join(OUT, "test_pct.parquet"))
for k in ("pooled_856", "held_sep_oct", "fresh_130", "pooled_no_ph_mention"):
    print(k, res[k]["n"]); [print(f"  {a:22s}", v) for a, v in res[k].items() if a != "n"]
print("testimonial rate by set", res["testimonial_rate"])
