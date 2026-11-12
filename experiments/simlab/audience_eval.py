"""Does the simulation know the audience? Hacker News (Show HN) vs Product Hunt (orchestrator 04:35Z Nov 12).
Data: hn_posts (usersim_sim/tables) holds every Show HN post since 2025-02 with url and comment counts but no comment text;
comment text is fetched from the free public Algolia HN items API (one call per thread). PH comments come from the PH thread
dumps (cf dir). gemini-2.5-flash throughout (cutoff Jan 2025; every post and launch here is later).
Sets
  (a) Show HN posts 2026-08-01..10-31 with >= 10 comments and a product URL; a fixed random sample of N_A, truth from >= 8
      non-author comments.
  (b) products on BOTH sites: candidate pairs by product domain (app-store / GitHub paths by id or owner/repo) or exact name
      within 180 days, both threads with >= 5 comments, then confirmed by a flash "same product?" check; one pair per HN post
      and per PH launch; truth from >= 5 non-team comments on each side.
Inputs (product-only, identical for both framings): (a) the Show HN title without the prefix, the URL's domain and the post
text; (b) the PH name, tagline, description and domain.
Generators (BEST pipeline minus PH retrieval: flash, temperature 0.3, 6 reactions, "comment (why)"):
  HN    reactions framed as Hacker News commenters on a Show HN post
  PH    the same prompt framed as Product Hunt members on launch day
  HNR   HN + retrieval: themes of the 10 most similar EARLIER Show HN threads (gemini-embedding; dated strictly before the
        target, other domains), condensed by flash-lite (themes only)
  GEN   a fixed generic HN list (alternatives / open source & self-hosting / pricing & business model / privacy & data /
        licence / how it works & which model / reliability / unclear landing page)
  SHUF  the HN arm's output for another, random post
  Concern lists: a separate ranked call ("6 critical points <audience> will raise, most likely first") for HN and PH; GEN's
  first 3 items; SHUF = HN list of another post.
Truth (flash extraction, as in ceiling.py): up to 8 themes, 6 critical themes, 6 questions, from up to 60 comments.
Judges (same blinded prompts as reactions_eval / concerns_rank): themes recall / precision; critical recall and question
recall (JUDGE a_covered with A = the critical / question truth); concerns p@3 / hit@3 (JC).
Split-half bar on (a) posts with >= 16 comments (one split), as in ceiling.py.
Cross test on (b): each framing scored against both communities' truth; interaction =
  (HN@hn - PH@hn) - (HN@ph - PH@ph), paired bootstrap over pairs.
Post / pair bootstrap 95% CIs. Spend guard at $5.8.
    python audience_eval.py <showhn.parquet> <pairs.parquet> <cf dir> <launches dir> <sites.jsonl> <out dir> [N_A]
"""
import concurrent.futures as cf, glob, gzip, hashlib, html, json, os, random, re, subprocess, sys, time, urllib.request
from urllib.parse import urlparse
import numpy as np, pandas as pd
tb = lambda x: x if isinstance(x, bool) else str(x).strip().lower() in ("true", "yes", "1")

SHN, PAIRS, CFD, LDIR, SITES, OUT = sys.argv[1:7]; N_A = int(sys.argv[7]) if len(sys.argv) > 7 else 150
os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
VX = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/{m}:generateContent"
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-flash-lite": (0.10, 0.40)}
_tok = {"t": "", "at": 0}; USD = {"usd": 0.0}; CAP = 5.8


def token():
    if time.time() - _tok["at"] > 300:
        _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
    return _tok["t"]


def post(url, body):
    for i in range(6):
        try:
            req = urllib.request.Request(url, json.dumps(body).encode(), {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=180))
        except Exception as e:  # noqa: BLE001
            print("retry", i, str(e)[:100], flush=True); time.sleep(4 * (i + 1))
    return None


def gem(prompt, maxtok=2000, temp=0.0, model="gemini-2.5-flash"):
    if USD["usd"] > CAP: return None
    j = post(VX.format(m=model), {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
             "generationConfig": {"temperature": temp, "maxOutputTokens": maxtok, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}})
    if not j: return None
    u = j.get("usageMetadata", {}); pi, po = PRICE[model]
    USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * pi + u.get("candidatesTokenCount", 0) / 1e6 * po
    try: return json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"]))
    except Exception: return None  # noqa: BLE001


def embed(texts):
    out = []
    for i in range(0, len(texts), 200):
        j = post(EMB, {"instances": [{"content": t[:2000], "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]], "parameters": {"outputDimensionality": 256}})
        out.append(np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32))
    E = np.vstack(out); return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


cache_f = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(key, fn):
    if key not in K or K[key] is None: K[key] = fn()
    return K[key]
num = lambda l: "\n".join(f"{k+1}. {t}" for k, t in enumerate(l))
clean = lambda t: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
dom = lambda u: re.sub(r"^www\.", "", (urlparse(u or "").netloc or "").lower().split(":")[0])


# ---------- HN threads (Algolia items API, free/public) ----------
def hn_thread(pid):
    for i in range(5):
        try:
            req = urllib.request.Request(f"https://hn.algolia.com/api/v1/items/{pid}", headers={"User-Agent": "research-backtest"})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:  # noqa: BLE001
            print("hn retry", pid, str(e)[:80], flush=True); time.sleep(3 * (i + 1))
    return None
TH_F = os.path.join(OUT, "hn_threads.json"); TH = json.load(open(TH_F)) if os.path.exists(TH_F) else {}
def hn_comments(pid):
    pid = str(pid)
    if pid not in TH:
        j = hn_thread(pid)
        if j is None: return []
        op = j.get("author"); out = []
        def walk(n):
            for c in n.get("children") or []:
                t = clean(c.get("text"))
                if c.get("author") and c.get("author") != op and len(t) > 15: out.append(t)
                walk(c)
        walk(j); TH[pid] = out
    return TH[pid]


# ---------- data ----------
P = pd.read_parquet(SHN); P["post_id"] = P.post_id.astype(str); P["name"] = P.title.str.replace(r"(?i)^show hn:\s*", "", regex=True); P["dom"] = P.url.fillna("").map(dom)
byp = {r.post_id: r for r in P.itertuples()}
A0 = P[(P.day >= "2026-08-01") & (P.day <= "2026-10-31") & (P.num_comments >= 10) & P.url.fillna("").str.startswith("http")]
print("Show HN Aug-Oct >= 10 comments with url", len(A0), flush=True)
ids = list(A0.post_id); random.Random(0).shuffle(ids)
with cf.ThreadPoolExecutor(8) as ex: list(ex.map(hn_comments, ids[: int(N_A * 1.4)]))
SA = [p for p in ids[: int(N_A * 1.4)] if len(TH.get(p, [])) >= 8][:N_A]
print("set (a) posts", len(SA), flush=True)

L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["id"] = L.id.astype(str); L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set()) for m, p in zip(L.makers, L.poster)]
bys = {s: r for s, r in zip(L.slug, L.itertuples())}; byid = {r.id: r for r in L.itertuples()}
U = {}
for l in open(SITES):
    x = json.loads(l)
    if x.get("url"): U[x["id"]] = x["url"]
PR = pd.read_parquet(PAIRS); PR["id"] = PR.id.astype(str); PR["post_id"] = PR.post_id.astype(str)
need = set(PR.slug); phc = {}
for f in sorted(glob.glob(os.path.join(CFD, "page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in need: continue
        r = bys[p_["slug"]]
        def walk(n):
            u = ((n.get("user") or {}).get("username") or "").lower(); t = clean(n.get("bodyHtml"))
            if u not in r.team and len(t) > 15: phc.setdefault(p_["slug"], {})[n.get("id")] = t
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
with cf.ThreadPoolExecutor(8) as ex: list(ex.map(hn_comments, sorted(set(PR.post_id))))
json.dump(TH, open(TH_F, "w"))
SAME = """Are these two launch posts about the SAME product (same product from the same makers; a different product with a
similar name is NOT the same)? Return JSON {{"same": true/false}}.
Product Hunt: {a}
Hacker News (Show HN): {b}"""
def same(r):
    l, p = byid[r.id], byp[r.post_id]
    a = f"{l.name} - {l.tagline}. {(l.description or '')[:600]} (site: {U.get(r.id, '')})"; b = f"{p.title} (url: {p.url}). {clean(p.text)[:600]}"
    return tb((gem(SAME.format(a=a, b=b), 50) or {}).get("same", False))
PR = PR[[len(phc.get(s, {})) >= 5 and len(TH.get(p, [])) >= 5 for s, p in zip(PR.slug, PR.post_id)]].copy()
with cf.ThreadPoolExecutor(8) as ex: PR["same"] = list(ex.map(lambda r: run(f"same|{r.id}|{r.post_id}", lambda: same(r)), PR.itertuples()))
PB = PR[PR.same].sort_values(["num_comments"], ascending=False).drop_duplicates("post_id").drop_duplicates("id")
PB = PB.head(3) if os.environ.get("SMOKE") else PB
print("pairs: candidates with >= 5 comments both sides", len(PR), "confirmed same product", int(PR.same.sum()), "unique pairs", len(PB), flush=True)

# ---------- prompts ----------
AUD = {"HN": ("Hacker News", "Hacker News commenters on a Show HN post", "as they'd write in a Hacker News thread"),
       "PH": ("Product Hunt", "Product Hunt members on launch day", "as they'd write in Product Hunt launch comments")}
REACT = """Simulate {where} reactions to a product from 6 distinct kinds of {who}.
Product: {name}
Site: {site}
Description (from the maker):
{desc}

Write one reaction for each of 6 distinct, realistic kinds of {who} (choose the kinds yourself; each is a TYPE of person, not a
real individual). Stay grounded in the description: do not invent features. Mix enthusiasm and skepticism the way this
community really does. Never use real names or @handles.
Return JSON: {{"reactions": [{{"type": "<kind of person>", "comment": "1-3 sentences {how}", "why": "one short reason"}}]}}"""
CONC = """Product: {name}
Site: {site}
Description (from the maker):
{desc}

List the 6 critical points (objections, doubting questions, feature requests) that {who} are most likely to raise about THIS
product, most likely first. Be specific to the product; do not invent features.
Return JSON {{"concerns": ["<one sentence>", ...]}}"""
NT = """Below are real user comments on a past Show HN post. Summarise the distinct points users raised as short themes
(praise, objection, question, feature request, comparison). Do not quote; paraphrase; no names or handles.
Return JSON {{"themes": ["<type>: <theme>", ...]}} with at most 6 themes.
Comments:
{c}"""
GEN = ["Why not just use an existing alternative - how is this different from the established tools?",
       "Is it open source, and can I self-host it?",
       "What is the pricing / business model, and will it stay free?",
       "Privacy: what data is collected or sent to third-party servers / LLM APIs?",
       "Licence concerns: the licence is restrictive or not truly open source.",
       "How does it work under the hood, and which model or stack does it use?",
       "Skepticism about reliability and accuracy in real use.",
       "The landing page does not explain clearly what it does; a demo or examples are needed."]
EX = """Below are real user comments on a product launch (makers' own comments removed). Return JSON with three lists:
"themes": the main themes users raised (praise, objections/concerns, questions, feature requests, comparisons) as
  [{{"theme": "<one specific sentence>", "n_comments": <int>}}], at most 8, most frequent first (generic thanks at most one theme);
"critical": ONLY critical themes (objections/concerns, doubting questions, feature requests), at most 6, most frequent first;
"questions": ONLY questions users asked the makers, at most 6, most frequent first.
Comments:
{c}"""
JUDGE = """List A = themes real users raised about a product. List B = candidate themes.
For each item in A, say whether some item in B substantially covers the same point (same concern/praise/question/request,
not merely the same broad area). For each item in B, say whether it substantially matches some item in A.
Return JSON {{"a_covered": [true/false per A item], "b_present": [true/false per B item]}}.
A:
{a}
B:
{b}"""
JC = """List A = critical points real users raised about a product launch (objections, doubting questions, feature requests).
List B = a ranked list of predicted concerns. For each item in B, does it substantially match some item in A (the same specific
concern, not merely the same broad area)? Return JSON {{"b_matches": [true/false per B item]}}
A:
{a}
B:
{b}"""


def inp_a(p): r = byp[p]; return dict(name=r.name, site=r.dom or r.url, desc=(clean(r.text) or "(no text; the title is all the maker wrote)")[:1500])
def inp_b(i): r = byid[i]; return dict(name=f"{r.name} - {r.tagline}", site=dom(U.get(i, "")) or "unknown", desc=(r.description or "")[:1500])
def react(inp, aud, extra=""):
    where, who, how = AUD[aud]
    a = gem(REACT.format(where=where, who=who, how=how, **inp) + extra, 3000, 0.3) or {}
    return [f"{x.get('comment', '')} ({x.get('why', '')})" for x in (a.get("reactions") or []) if isinstance(x, dict)][:6]
def conc(inp, aud): return [str(x) for x in ((gem(CONC.format(who=AUD[aud][1], **inp), 1200, 0.3) or {}).get("concerns") or [])][:6]
def truth(cs): return gem(EX.format(c="\n".join(f"- {t[:400]}" for t in cs[:60])), 2000) or {}
def themes(x): return [str(t.get("theme")) for t in (x.get("themes") or []) if isinstance(t, dict) and t.get("theme")][:8]
def judge_rp(real, cand):
    if not real or not cand: return None
    a = gem(JUDGE.format(a=num(real), b=num(cand)), 800) or {}
    ac, bp = [tb(x) for x in a.get("a_covered", [])], [tb(x) for x in a.get("b_present", [])]
    return (float(np.mean(ac)), float(np.mean(bp))) if len(ac) == len(real) and len(bp) == len(cand) else None
def judge_p3(real, cand):
    if not real or not cand: return None
    bm = (gem(JC.format(a=num(real), b=num(cand[:3])), 300) or {}).get("b_matches"); bm = [tb(x) for x in bm] if isinstance(bm, list) else bm
    return (float(np.mean(bm)), float(any(bm))) if isinstance(bm, list) and len(bm) == len(cand[:3]) else None


# ---------- retrieval pool for HNR: earlier Show HN posts with >= 10 comments ----------
POOL = P[(P.day >= "2026-03-01") & (P.num_comments >= 10)].reset_index(drop=True)
EP = embed([f"{r.name}. {clean(r.text)[:1200]}" for r in POOL.itertuples()]); pidx = {p: i for i, p in enumerate(POOL.post_id)}
def neighbours(p, k=10):
    r = byp[p]; v = EP @ EP[pidx[p]]
    ok = (POOL.day < r.day).to_numpy() & (POOL.dom != r.dom).to_numpy() & (POOL.post_id != p).to_numpy()
    return [POOL.post_id[i] for i in np.argsort(-np.where(ok, v, -9))[:k]]
def nb_themes(o):
    return run(f"nbth|{o}", lambda: ((gem(NT.format(c="\n".join(f"- {t[:300]}" for t in hn_comments(o)[:30])), 800, 0.0, "gemini-2.5-flash-lite") or {}).get("themes") or [])[:6])


# ---------- set (a) ----------
def work_a(p):
    inp = inp_a(p); r = {"p": p, "n": len(TH[p])}
    T = run(f"truth|hn|{p}", lambda: truth(TH[p])); tt, tc, tq = themes(T), (T.get("critical") or [])[:6], (T.get("questions") or [])[:6]
    out = {"HN": run(f"r|HN|a|{p}", lambda: react(inp, "HN")), "PH": run(f"r|PH|a|{p}", lambda: react(inp, "PH"))}
    nbt = [t for o in neighbours(p) for t in nb_themes(o)][:60]
    out["HNR"] = run(f"r|HNR|a|{p}", lambda: react(inp, "HN", "\n\nFor grounding: Hacker News commenters on similar earlier Show HN posts raised these points (other products, not this one; reuse only what plausibly applies here):\n" + "\n".join(f"- {t}" for t in nbt)))
    out["GEN"] = GEN
    cl = {"HN": run(f"c|HN|a|{p}", lambda: conc(inp, "HN")), "PH": run(f"c|PH|a|{p}", lambda: conc(inp, "PH")), "GEN": GEN[:3]}
    r["_out"], r["_cl"] = out, cl
    for arm, o in out.items():
        r[f"rp|{arm}"] = run(f"jrp|a|{arm}|{p}", lambda: judge_rp(tt, o)); r[f"cr|{arm}"] = run(f"jcr|a|{arm}|{p}", lambda: judge_rp(tc, o)); r[f"qr|{arm}"] = run(f"jqr|a|{arm}|{p}", lambda: judge_rp(tq, o))
    for arm, o in cl.items(): r[f"p3|{arm}"] = run(f"jp3|a|{arm}|{p}", lambda: judge_p3(tc, o))
    r["_t"] = (tt, tc, tq)
    if len(TH[p]) >= 16:                                   # split-half bar (one split)
        cs = TH[p]; idx = np.random.default_rng(int(hashlib.md5(p.encode()).hexdigest()[:6], 16)).permutation(len(cs))
        HA = run(f"half|A|{p}", lambda: truth([cs[i] for i in idx[: len(cs) // 2]])); HB = run(f"half|B|{p}", lambda: truth([cs[i] for i in idx[len(cs) // 2:]]))
        bt, bc = themes(HB), (HB.get("critical") or [])[:6]
        r["ceil_rp"] = run(f"cel|rp|{p}", lambda: judge_rp(bt, themes(HA))); r["ceil_p3"] = run(f"cel|p3|{p}", lambda: judge_p3(bc, (HA.get("critical") or [])[:6]))
        r["oursB_rp"] = run(f"oursB|rp|{p}", lambda: judge_rp(bt, out["HNR"])); r["oursB_rpHN"] = run(f"oursB|rpHN|{p}", lambda: judge_rp(bt, out["HN"]))
        r["oursB_p3"] = run(f"oursB|p3|{p}", lambda: judge_p3(bc, cl["HN"]))
    return r
with cf.ThreadPoolExecutor(10) as ex: RA = list(ex.map(work_a, SA))
json.dump(K, open(cache_f, "w")); print("set (a) done usd", round(USD["usd"], 3), flush=True)
# SHUF: HN arm output / concern list of another post (derangement)
perm = list(range(len(RA))); random.Random(1).shuffle(perm); perm = perm[1:] + perm[:1]
def work_shuf(i):
    r, o = RA[i], RA[perm[i]]; tt, tc, tq = r["_t"]; p = r["p"]
    r["rp|SHUF"] = run(f"jrp|a|SHUF|{p}", lambda: judge_rp(tt, o["_out"]["HN"])); r["cr|SHUF"] = run(f"jcr|a|SHUF|{p}", lambda: judge_rp(tc, o["_out"]["HN"]))
    r["qr|SHUF"] = run(f"jqr|a|SHUF|{p}", lambda: judge_rp(tq, o["_out"]["HN"])); r["p3|SHUF"] = run(f"jp3|a|SHUF|{p}", lambda: judge_p3(tc, o["_cl"]["HN"]))
with cf.ThreadPoolExecutor(10) as ex: list(ex.map(work_shuf, range(len(RA))))
json.dump(K, open(cache_f, "w")); print("shuf done usd", round(USD["usd"], 3), flush=True)


# ---------- set (b): 2x2 cross test ----------
def work_b(row):
    i, p, s = row.id, row.post_id, row.slug; inp = inp_b(i); r = {"pair": f"{i}|{p}", "n_hn": len(TH[p]), "n_ph": len(phc[s])}
    TH_ = run(f"truth|hn|{p}", lambda: truth(TH[p])); TP_ = run(f"truth|ph|{s}", lambda: truth(list(phc[s].values())))
    for aud in ("HN", "PH"):
        o = run(f"r|{aud}|b|{i}", lambda: react(inp, aud)); c = run(f"c|{aud}|b|{i}", lambda: conc(inp, aud))
        for comm, T in (("hn", TH_), ("ph", TP_)):
            tt, tc = themes(T), (T.get("critical") or [])[:6]
            r[f"rp|{aud}@{comm}"] = run(f"jrp|b|{aud}|{comm}|{i}|{p}", lambda: judge_rp(tt, o)); r[f"cr|{aud}@{comm}"] = run(f"jcr|b|{aud}|{comm}|{i}|{p}", lambda: judge_rp(tc, o))
            r[f"p3|{aud}@{comm}"] = run(f"jp3|b|{aud}|{comm}|{i}|{p}", lambda: judge_p3(tc, c))
    return r
with cf.ThreadPoolExecutor(10) as ex: RB = list(ex.map(work_b, PB.itertuples()))
json.dump(K, open(cache_f, "w")); json.dump(TH, open(TH_F, "w")); print("set (b) done usd", round(USD["usd"], 3), flush=True)


# ---------- metrics ----------
def mb(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]
def col(R, k, j):
    return np.array([(r.get(k)[j] if r.get(k) else np.nan) for r in R], float)
ARMS = ["HN", "PH", "HNR", "GEN", "SHUF"]
res = {"design": __doc__.split("\n    python")[0], "data": {"showhn_aug_oct_ge10_with_url": int(len(A0)), "set_a_posts": len(SA),
       "pair_candidates_ge5_both": int(len(PR)), "pairs_confirmed": int(PR.same.sum()), "pairs_unique": int(len(PB)),
       "median_comments_a": float(np.median([r["n"] for r in RA]))}, "a": {}, "a_paired": {}, "bar": {}, "b": {}, "b_cross": {}}
for arm in ARMS:
    res["a"][arm] = {"theme_recall": mb(col(RA, f"rp|{arm}", 0)), "theme_precision": mb(col(RA, f"rp|{arm}", 1)), "critical_recall": mb(col(RA, f"cr|{arm}", 0)),
                     "question_recall": mb(col(RA, f"qr|{arm}", 0))}
    if arm in ("HN", "PH", "GEN", "SHUF"): res["a"][arm] |= {"concern_p3": mb(col(RA, f"p3|{arm}", 0)), "concern_hit3": mb(col(RA, f"p3|{arm}", 1))}
for a, b in (("HN", "PH"), ("HNR", "HN"), ("HN", "GEN"), ("HNR", "GEN"), ("HN", "SHUF"), ("PH", "GEN")):
    d = {m: mb(col(RA, f"{k}|{a}", j) - col(RA, f"{k}|{b}", j)) for m, k, j in (("theme_recall", "rp", 0), ("theme_precision", "rp", 1), ("critical_recall", "cr", 0), ("question_recall", "qr", 0))}
    if a != "HNR" and b != "HNR": d |= {"concern_p3": mb(col(RA, f"p3|{a}", 0) - col(RA, f"p3|{b}", 0)), "concern_hit3": mb(col(RA, f"p3|{a}", 1) - col(RA, f"p3|{b}", 1))}
    res["a_paired"][f"{a} - {b}"] = d
Rh = [r for r in RA if "ceil_rp" in r]
res["bar"] = {"posts": len(Rh), "bar_recall": mb(col(Rh, "ceil_rp", 0)), "bar_precision": mb(col(Rh, "ceil_rp", 1)), "bar_concern_p3": mb(col(Rh, "ceil_p3", 0)),
              "bar_concern_hit3": mb(col(Rh, "ceil_p3", 1)), "HNR_vs_halfB_recall": mb(col(Rh, "oursB_rp", 0)), "HNR_vs_halfB_precision": mb(col(Rh, "oursB_rp", 1)),
              "HN_vs_halfB_recall": mb(col(Rh, "oursB_rpHN", 0)), "HN_vs_halfB_precision": mb(col(Rh, "oursB_rpHN", 1)), "HN_concern_p3_vs_halfB": mb(col(Rh, "oursB_p3", 0))}
for aud in ("HN", "PH"):
    for comm in ("hn", "ph"):
        res["b"][f"{aud} framing @ {comm} comments"] = {"theme_recall": mb(col(RB, f"rp|{aud}@{comm}", 0)), "theme_precision": mb(col(RB, f"rp|{aud}@{comm}", 1)),
                                                        "critical_recall": mb(col(RB, f"cr|{aud}@{comm}", 0)), "concern_p3": mb(col(RB, f"p3|{aud}@{comm}", 0))}
for m, k, j in (("theme_recall", "rp", 0), ("theme_precision", "rp", 1), ("critical_recall", "cr", 0), ("concern_p3", "p3", 0)):
    hh, ph_h, hp, pp = (col(RB, f"{k}|{a}@{c}", j) for a, c in (("HN", "hn"), ("PH", "hn"), ("HN", "ph"), ("PH", "ph")))
    res["b_cross"][m] = {"HN-PH framing @ hn": mb(hh - ph_h), "HN-PH framing @ ph": mb(hp - pp), "interaction": mb((hh - ph_h) - (hp - pp)),
                         "HN framing: hn - ph comments": mb(hh - hp), "PH framing: ph - hn comments": mb(pp - ph_h)}
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "audience_eval.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
