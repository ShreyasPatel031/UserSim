"""Prove /try fixes before the website builds them (orchestrator 10:15Z Nov 12). Uses the website's own code (origin/claude/ph-website
mvp/ph_site: safe_fetch, try_sim.READ_PROMPT on flash-lite, try_sim._band_score with launch_band.json, person_e5.embed) as a library.
Launches: every ranked launch of Oct 27 - Nov 10 2026 with a product URL (at-launch primary_link, else the first non-PH link in the
maker's first comment); each site fetched ONCE by safe_fetch (http rewritten to https only because this container's proxy mode
refuses http), then read with the site's READ_PROMPT.
1. Band inputs (score -> percentile among the band's cuts -> decile band):
   (a) SITE now: name, tagline, summary + page_excerpt[:600], page-read topics
   (b) READ: name + tagline + 2-sentence summary only, page-read topics
   (c) REWRITE: a flash-lite rewrite of the page read into PH launch style (name, <= 60-char tagline, <= 260-char description,
       3 topics from the PH vocabulary), then the band
   (d) PH: the real PH name / tagline / description / topics (reference)
   Spearman of the band percentile with -final rank (pooled over launches), band coverage of the true rank; paired bootstrap vs (a).
2. Concerns and questions (launches with >= 5 identity-free truth comments): RANKED concerns (critic D_category + retrieved
   neighbour themes + category base list, scored by neighbour frequency + agreement + Gemini likelihood; the reactions generator is
   left out) and the single-call question generator, each fed (i) the page-read name/tagline/summary, (ii) the raw page excerpt,
   (iii) the PH description. Blinded judges as concerns_rank / questions_rank; p@3 / hit@3, paired.
3. Fetch failures: for every launch whose fetch or page read failed, retry (i) the root of the same domain, (ii) the at-launch
   primary_link (PH "website" target) when held and different; share recovered without a headless browser.
    python try_fixes.py <ph-website worktree> <scratchpad> <out dir>
"""
import asyncio, glob, json, os, re, sys, time, html as _html
from urllib.parse import urlparse
import numpy as np, pandas as pd
from scipy.stats import spearmanr

WT, SP, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True)
os.environ["TRY_SIGNING_KEY"] = "local-dummy-key-for-offline-eval-0123456789"; os.environ["TRY_LOCAL_LIMITS"] = "1"
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(SP, "gcp_key.json")); os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox")
sys.path[:0] = [WT, os.path.join(WT, "src")]
from mvp.ph_site import try_sim, safe_fetch, gcs, person_e5  # noqa: E402
from capability import gemini_config as GC  # noqa: E402
rng = np.random.default_rng(0); USE = {}
PRICE = {"gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-flash": (0.30, 2.50)}
cache_f = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
save = lambda: json.dump(K, open(cache_f, "w"))


async def chat(prompt, model, tok=1500, temp=0.0):
    t = await GC.gemini_chat([{"role": "user", "content": prompt}], model=model, temperature=temp, max_retries=3, max_output_tokens=tok)
    u = USE.setdefault(model, [0, 0]); u[0] += len(prompt); u[1] += len(t or ""); return t


async def cj(prompt, model="gemini-2.5-flash", tok=1500, temp=0.0):
    try: return GC.extract_json(await chat(prompt, model, tok, temp)) or {}
    except Exception: return {}  # noqa: BLE001

# ---------- launches / urls / truth ----------
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & (L.day >= "2026-10-27") & (L.day <= "2026-11-10")].copy(); L["id"] = L.id.astype(str); L["rank"] = L.daily_rank.astype(float)
U = json.load(open(os.path.join(SP, "try_e2e/urls.json"))); PL = {json.loads(l)["id"]: json.loads(l)["url"] for l in open(os.path.join(SP, "try_e2e/primary_links.jsonl"))}
L = L[L.id.isin(U)].reset_index(drop=True)
C = {}
for f in glob.glob(os.path.join(SP, "try_e2e/apic/*/*.jsonl")):
    for l in open(f): x = json.loads(l); C[x["comment_id"]] = x
clean = lambda t: re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
bypost = {}
for x in C.values(): bypost.setdefault(str(x["post_id"]), []).append(x)
truth_c = {}
for p, cs in bypost.items():
    tops = sorted([(c["createdAt"], c["commenter_user_id"]) for c in cs if not c.get("parentId")]); mk = tops[0][1] if tops else None
    truth_c[p] = [clean(c["body"]) for c in sorted(cs, key=lambda c: c["createdAt"]) if c["commenter_user_id"] != mk and len(clean(c["body"])) > 15]
IDX = try_sim.index(); VOCAB = IDX["meta"]["vocab"]; LB = gcs.read_json("results/web/launch_band.json")
print("launches with url", len(L), "with truth >= 5", int(sum(len(truth_c.get(i, [])) >= 5 for i in L.id)), flush=True)


def band(name, tagline, desc, topics):
    sc = try_sim._band_score(LB, name or "", tagline or "", desc or "", topics or []); pct = sum(1 for c in LB["score_percentile_cuts"] if c < sc)
    b = LB["bands"][min(9, pct // 10)]; return {"pct": pct, "lo": int(b["daily_rank_p10_p50_p90"][0]), "hi": int(b["daily_rank_p10_p50_p90"][2])}


async def read_page(url):
    norm = await safe_fetch.check_url(url); page = await safe_fetch.fetch_product(norm)
    if len((page["text"] or "").strip()) < 80: raise ValueError("almost no readable text")
    prompt = try_sim.READ_PROMPT.format(url=page["url"], title=page["title"], desc=page["description"], text=page["text"][:9000], pricing=page["pricing_text"][:2500], vocab=", ".join(VOCAB))
    a = GC.extract_json(await chat(prompt, try_sim.MODEL, 1500, 0.2))
    if a.get("problem"): raise ValueError("page judge: " + str(a["problem"])[:120])
    a["topics"] = [t for t in (a.get("topics") or []) if t in VOCAB][:4] or ["Productivity"]
    a["page_excerpt"] = (page["description"] + "\n" + page["text"])[:2500]; a["title"] = page["title"]; return a


REWRITE = """Rewrite this product's own web page as its Product Hunt launch post. Use ONLY the facts below; do not invent features,
numbers or customers.
Page title: {title}
Name: {name}
Page-read tagline: {tagline}
Page-read summary: {summary}
Audience: {audience}
Page text (excerpt):
{excerpt}

Allowed Product Hunt topics (choose exactly 3, most specific first, exact spelling): {vocab}
Return JSON {{"name": "product name", "tagline": "<= 60 characters, Product Hunt style", "description": "<= 260 characters, what it
does and for whom, in the maker's voice", "topics": ["...", "...", "..."]}}"""
fix = lambda u: "https://" + u[len("http://"):] if u.startswith("http://") else u


async def one(r, sem):
    async with sem:
        key = f"p|{r.id}"
        if key not in K:
            t0 = time.time(); rec = {}
            try:
                a = await read_page(fix(U[r.id])); rec["read"] = {k: a.get(k) for k in ("name", "tagline", "summary", "topics", "audience", "page_excerpt", "title")}
                rw = await cj(REWRITE.format(title=a.get("title"), name=a.get("name"), tagline=a.get("tagline"), summary=a.get("summary"), audience=a.get("audience"),
                                             excerpt=a["page_excerpt"][:1500], vocab=", ".join(VOCAB)), try_sim.MODEL, 600, 0.2)
                rw["topics"] = [t for t in (rw.get("topics") or []) if t in VOCAB][:3] or a["topics"][:3]; rec["rewrite"] = rw
            except Exception as e:  # noqa: BLE001
                rec["fail"] = f"{type(e).__name__}: {str(e)[:140]}"
            rec["lat"] = time.time() - t0; K[key] = rec; save()
        return K[key]


async def main():
    sem = asyncio.Semaphore(6); return await asyncio.gather(*[one(r, sem) for r in L.itertuples()])
P = asyncio.run(main())
L["rec"] = P; ok = L.rec.map(lambda x: "fail" not in x)
print("fetched+read ok", int(ok.sum()), "of", len(L), flush=True)

# ---------- 1. band ----------
rows = []
for r in L[ok].itertuples():
    rd, rw = r.rec["read"], r.rec["rewrite"]; tp = [t for t in (json.loads(r.topics) if isinstance(r.topics, str) and r.topics.startswith("[") else []) if t in VOCAB][:4] or ["Productivity"]
    B = {"a_site": band(rd["name"], rd["tagline"], (rd.get("summary") or "") + " " + (rd.get("page_excerpt") or "")[:600], rd["topics"]),
         "b_read": band(rd["name"], rd["tagline"], rd.get("summary") or "", rd["topics"]),
         "c_rewrite": band(rw.get("name") or rd["name"], rw.get("tagline") or "", rw.get("description") or "", rw["topics"]),
         "d_ph": band(r.name, r.tagline or "", r.description or "", tp)}
    rows.append({"id": r.id, "day": r.day, "rank": r.rank, **{f"{k}_pct": v["pct"] for k, v in B.items()}, **{f"{k}_cov": float(v["lo"] <= r.rank <= v["hi"]) for k, v in B.items()}})
D = pd.DataFrame(rows); ARMS = ["a_site", "b_read", "c_rewrite", "d_ph"]


def sp_boot(cols, B=2000):
    out = {c: [] for c in cols}; n = len(D)
    for _ in range(B):
        i = rng.integers(0, n, n); s = D.iloc[i]
        for c in cols: out[c].append(spearmanr(s[f"{c}_pct"], -s["rank"]).correlation)
    return out
bs = sp_boot(ARMS); res = {"design": __doc__.split("\n    python")[0], "launches_with_url": len(L), "fetched_and_read": int(ok.sum()), "band": {}}
for a in ARMS:
    v = spearmanr(D[f"{a}_pct"], -D["rank"]).correlation; cv = D[f"{a}_cov"]
    res["band"][a] = {"spearman": round(float(v), 3), "ci": [round(float(x), 3) for x in np.percentile(bs[a], [2.5, 97.5])], "coverage": round(float(cv.mean()), 3), "n": int(len(D))}
    if a != "a_site":
        d = np.array(bs[a]) - np.array(bs["a_site"]); res["band"][a]["minus_a (paired)"] = [round(float(x), 3) for x in np.percentile(d, [2.5, 50, 97.5])]
    res["band"][a]["spearman_with_d_ph_pct"] = round(float(spearmanr(D[f"{a}_pct"], D["d_ph_pct"]).correlation), 3)
print(json.dumps(res["band"]), flush=True)

# ---------- 2. concerns / questions ----------
RBE = np.load(os.path.join(SP, "rbundle/reactions_retrieval_v1.npz"))["emb"].astype(np.float32); RBM = json.load(open(os.path.join(SP, "rbundle/reactions_retrieval_v1.json")))
DCAT = ("List the 6 criticisms most likely from real users: first the complaints users of this product CATEGORY almost always raise (2-3), then the "
        "ones SPECIFIC to this product (the rest). Write them as they would appear in launch-day comments (objections, questions to the maker, feature requests). Do not invent features.\n"
        "Product: {name}\nDescription: {desc}\nReturn JSON {{\"criticisms\": [\"<one specific sentence>\", ...]}}")
QG = """A new product is launching on Product Hunt today.
Product: {name} - {tagline}
Description: {desc}
List the 6 questions users are most likely to ask the makers in the launch comments in the first hours, most likely first.
Be specific to this product; do not invent features. Return JSON {{"questions": ["...", ...]}}"""
LIKE = """A new product is launching on Product Hunt.
Product: {name} - {tagline}
Description: {desc}
Below are candidate {what} users might raise in the launch comments.
Rate how likely real users are to raise each one for THIS product, 1 (unlikely) to 5 (very likely).
Return JSON {{"ratings": [1-5 per candidate, in order]}}
{c}"""
EX = """Below are real user comments on a product launch (makers' own comments removed). Return JSON with two lists:
"critical": ONLY critical themes (objections/concerns, doubting questions, feature requests), at most 6, most frequent first;
"questions": ONLY questions users asked the makers, at most 6, most frequent first.
Comments:
{c}"""
JC = """List A = critical points real users raised about a product launch (objections, doubting questions, feature requests).
List B = a ranked list of predicted concerns. For each item in B, does it substantially match some item in A (the same specific
concern, not merely the same broad area)? Return JSON {{"b_matches": [true/false per B item]}}
A:
{a}
B:
{b}"""
JQ = """List A = questions real users asked the makers of a product launch. List B = a ranked list of predicted questions or
reactions. For each item in B, does it substantially match some question in A (asks for the same specific thing, not merely the
same broad area)? Return JSON {{"b_matches": [true/false per B item]}}
A:
{a}
B:
{b}"""
CRITRE = re.compile(r"^\s*(objection|question|feature request|feature_request)\s*:\s*", re.I); QRE = re.compile(r"^\s*question\s*:\s*", re.I)
tb = lambda x: x if isinstance(x, bool) else str(x).strip().lower() in ("true", "yes", "1")
num = lambda l: "\n".join(f"{k+1}. {str(t)[:300]}" for k, t in enumerate(l))


import subprocess, urllib.request  # noqa: E402
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
_tk = {"t": "", "at": 0}
def _token():
    if time.time() - _tk["at"] > 300: _tk["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tk["at"] = time.time()
    return _tk["t"]
def _emb_sync(texts):                                   # same model / task / dimension as person_e5.embed, batched
    out = []
    for i in range(0, len(texts), 200):
        for a in range(6):
            try:
                req = urllib.request.Request(EMB, json.dumps({"instances": [{"content": t[:1200], "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]], "parameters": {"outputDimensionality": 256}}).encode(),
                                             {"Authorization": "Bearer " + _token(), "Content-Type": "application/json"})
                j = json.load(urllib.request.urlopen(req, timeout=120)); break
            except Exception:  # noqa: BLE001
                time.sleep(3 * (a + 1))
        out.append(np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32))
    E_ = np.vstack(out); return E_ / (np.linalg.norm(E_, axis=1, keepdims=True) + 1e-9)
TCACHE = {}
for d_, rx_ in (("conc", r"^\s*(objection|question|feature request|feature_request)\s*:\s*"), ("qrank", r"^\s*(question)\s*:\s*")):
    allt = sorted({re.sub(rx_, "", t, flags=re.I) for m in json.load(open(os.path.join(SP, "rbundle/reactions_retrieval_v1.json"))) for t in m["themes"] if re.match(rx_, t, re.I)})
    E_ = np.load(os.path.join(SP, d_, "ct_emb.npy"))
    if len(E_) == len(allt): TCACHE.update(dict(zip(allt, E_)))
print("cached theme embeddings", len(TCACHE), flush=True)
async def emb(texts):
    miss = [t for t in dict.fromkeys(texts) if t not in TCACHE]
    if miss:
        for t, v in zip(miss, await asyncio.to_thread(_emb_sync, miss)): TCACHE[t] = v
    return np.vstack([TCACHE[t] for t in texts]).astype(np.float32)


async def ranked(name, tagline, desc, kind, day):
    q = (await emb([f"{name}. {tagline}. {desc[:800]}"]))[0]; sims = RBE @ q; nb = []
    for j in np.argsort(-sims):
        if RBM[j]["day"] >= day: continue
        nb.append(j)
        if len(nb) == 25: break
    rex = CRITRE if kind == "concerns" else QRE
    nth = [(rex.sub("", t), j) for j in nb for t in RBM[j]["themes"] if rex.match(t)]
    if kind == "concerns": gen = [str(x) for x in ((await cj(DCAT.format(name=f"{name} - {tagline}", desc=desc[:1500]), temp=0.3)).get("criticisms") or [])][:6]
    else: gen = [str(x) for x in ((await cj(QG.format(name=name, tagline=tagline, desc=desc[:1200]), temp=0.3)).get("questions") or [])][:6]
    if not nth: return gen[:5], gen
    NX = await emb([t for t, _ in nth]); own = np.array([j for _, j in nth]); SS = NX @ NX.T
    cnt = np.array([len(set(own[SS[i] >= 0.80])) for i in range(len(nth))]); retr, used = [], np.zeros(len(nth), bool)
    for i in np.argsort(-cnt):
        if used[i]: continue
        retr.append(nth[i][0]); used |= SS[i] >= 0.80
        if len(retr) == 8: break
    cands = [(t, "GEN") for t in gen] + [(t, "RETR") for t in retr]
    X = await emb([t for t, _ in cands]); S_ = X @ X.T; g = np.array([x for _, x in cands])
    a = np.array([len(set(own[(NX @ X[i]) >= 0.80])) for i in range(len(cands))], float)
    b = np.array([((S_[i] >= 0.80) & (g != g[i])).sum() for i in range(len(cands))], float)
    lk = (await cj(LIKE.format(name=name, tagline=tagline, desc=desc[:1200], what="concerns (objections, doubting questions, feature requests)" if kind == "concerns" else "questions to the makers", c=num([t for t, _ in cands])), tok=300)).get("ratings")
    c = np.array(lk if isinstance(lk, list) and len(lk) == len(cands) else [3] * len(cands), float)
    rk = lambda v: pd.Series(v).rank(pct=True).to_numpy(); sc = (rk(a) + rk(b) + rk(c)) / 3; out, used = [], np.zeros(len(cands), bool)
    for i in np.argsort(-sc):
        if used[i]: continue
        out.append(cands[i][0]); used |= S_[i] >= 0.90
        if len(out) == 5: break
    return out, gen


async def judge(JP, truth, lst):
    if not truth or not lst: return None
    bm = (await cj(JP.format(a=num(truth), b=num(lst[:3])), tok=300)).get("b_matches"); bm = [tb(x) for x in bm] if isinstance(bm, list) else None
    return (float(np.mean(bm)), float(any(bm))) if bm and len(bm) == len(lst[:3]) else None


async def cq(r, sem):
    async with sem:
        key = f"cq|{r.id}"
        if key in K: return K[key]
        rd = r.rec["read"]
        T = await cj(EX.format(c="\n".join(f"- {t[:400]}" for t in truth_c[r.id][:40])), tok=1500); tc, tq = (T.get("critical") or [])[:6], (T.get("questions") or [])[:6]
        inputs = {"read_summary": (rd["name"], rd.get("tagline") or "", rd.get("summary") or ""), "raw_excerpt": (rd["name"], rd.get("tagline") or "", rd.get("page_excerpt") or ""),
                  "ph_description": (r.name, r.tagline or "", r.description or "")}
        out = {}
        for k, (n, t, d) in inputs.items():
            cr, cg = await ranked(n, t, d, "concerns", r.day); qr, qg = await ranked(n, t, d, "questions", r.day)
            out[k] = {"c_ranked": await judge(JC, tc, cr), "c_gen": await judge(JC, tc, cg), "q_ranked": await judge(JQ, tq, qr), "q_gen": await judge(JQ, tq, qg)}
        K[key] = out; save(); return out
Q = L[ok & L.id.map(lambda i: len(truth_c.get(i, [])) >= 5)]
async def main2():
    sem = asyncio.Semaphore(5); return await asyncio.gather(*[cq(r, sem) for r in Q.itertuples()])
CQ = asyncio.run(main2()); res["concerns_questions"] = {"launches": len(Q)}


def mb(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs_ = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs_, 2.5)) * 100, 1), round(float(np.percentile(bs_, 97.5)) * 100, 1), int(len(v))]
get = lambda inp, m, j: np.array([(o[inp][m][j] if o.get(inp) and o[inp].get(m) else np.nan) for o in CQ], float)
for m in ("c_ranked", "c_gen", "q_ranked", "q_gen"):
    for j, lab in ((0, "p3"), (1, "hit3")):
        d = {inp: mb(get(inp, m, j)) for inp in ("read_summary", "raw_excerpt", "ph_description")}
        d["read_summary - raw_excerpt (paired)"] = mb(get("read_summary", m, j) - get("raw_excerpt", m, j))
        d["read_summary - ph_description (paired)"] = mb(get("read_summary", m, j) - get("ph_description", m, j))
        res["concerns_questions"][f"{m} {lab}"] = d
print(json.dumps(res["concerns_questions"])[:1500], flush=True)

# ---------- 3. fetch failure recovery ----------
async def retry(r):
    key = f"retry|{r.id}"
    if key in K: return K[key]
    u = fix(U[r.id]); p = urlparse(u); root = f"https://{p.netloc}/"; out = {"orig_fail": r.rec["fail"]}
    for lab, url in (("root", root), ("primary_link", fix(PL[r.id]) if r.id in PL and fix(PL[r.id]).rstrip("/") != u.rstrip("/") else None)):
        if not url or (lab == "root" and url.rstrip("/") == u.rstrip("/")): out[lab] = "same as original"; continue
        try: await read_page(url); out[lab] = "ok"
        except Exception as e: out[lab] = f"{type(e).__name__}: {str(e)[:100]}"  # noqa: BLE001
    K[key] = out; save(); return out
F = L[~ok]
async def main3():
    return [await retry(r) for r in F.itertuples()]
RT = asyncio.run(main3())
kind = lambda s: ("no readable text (JS-only)" if "readable text" in s else "HTTP 403" if "403" in s else "page judge refused" if "page judge" in s else "other: " + s.split(":")[0])
res["fetch_failures"] = {"failed": len(F), "share_of_launches": round(len(F) / len(L), 3), "by_kind": pd.Series([kind(x["orig_fail"]) for x in RT]).value_counts().to_dict(),
                         "recovered_by_root": int(sum(x.get("root") == "ok" for x in RT)), "recovered_by_primary_link": int(sum(x.get("primary_link") == "ok" for x in RT)),
                         "recovered_any": int(sum(x.get("root") == "ok" or x.get("primary_link") == "ok" for x in RT)),
                         "by_kind_recovered": pd.Series({k: int(sum((kind(x["orig_fail"]) == k) and (x.get("root") == "ok" or x.get("primary_link") == "ok") for x in RT)) for k in {kind(x["orig_fail"]) for x in RT}}).to_dict()}
res["latency_read_s_median"] = round(float(np.median([x["lat"] for x in L.rec])), 1)
res["gemini_usd_estimate_this_run"] = round(sum(v[0] / 4 / 1e6 * PRICE.get(m, (0.3, 2.5))[0] + v[1] / 4 / 1e6 * PRICE.get(m, (0.3, 2.5))[1] for m, v in USE.items()), 3)
json.dump(res, open(os.path.join(OUT, "try_fixes.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k not in ("design", "concerns_questions")}, indent=1, default=str))
