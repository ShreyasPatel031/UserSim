"""Is /try stable? (orchestrator 09:08Z Nov 12). 60 of the fresh 130 page-read launches (stratified by final rank, seed 0), all through
the site's own code (try_sim.step_page / step_text / step_reactions; band = _band_score with the served page band or, for pasted text,
the PH band, exactly as step_launch chooses). Gemini flash / flash-lite only.
  (a) reruns: the same URL 3x (fetch + read + band; reactions on runs 1-2); temp-0 read 2x (free fix: temperature 0)
  (b) page variants: the launch's linked page vs its root domain (when different)
  (c) pasted forms through step_text + PH band: real PH description; hero text (title + meta description + first heading of the fetched
      page); 2-sentence paraphrase; long marketing paraphrase (flash-lite, from the read, no new facts)
  control: a different product's outputs (fixed derangement) as the floor for every stability metric
Metrics: band percentile sd / share of pairs > 1 decile apart / Spearman across the 60; reactions agreement % (judge: does each B
reaction raise the same specific point as some A reaction), reactions precision vs real comment themes by input; ranked concerns /
questions overlap@3 between 2 reruns (30 launches) and vs a mismatched product; accuracy (Spearman with -rank) by input form.
    python try_stability.py <ph-website worktree> <scratchpad> <out dir>
"""
import os, sys, json, re
WT, SP0, OUTD = sys.argv[1:4]
SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "try_fixes.py")).read().split("\n")
TF = "\n".join(SRC[:118]) + "\n" + "\n".join(SRC[145:254])   # setup + cached fresh reads (no new calls) + ranked() / judge()
sys.argv = [sys.argv[0], WT, SP0, os.path.join(SP0, "try_fixes")]
exec(TF)
os.makedirs(OUTD, exist_ok=True); CF = os.path.join(OUTD, "cache.json"); C = json.load(open(CF)) if os.path.exists(CF) else {}
def csave(): json.dump(C, open(CF, "w"))
from mvp.ph_site import safe_fetch  # noqa: E402
LBP = gcs.read_json("site/launch_band_page_v1.json"); LBH = gcs.read_json("results/web/launch_band.json")
PHP = re.compile(r"(?i)(#\s*\d+\s*)?product of the (day|week|month)|#\s*1 product|product\s*hunt|upvotes?")
def pct(lb, s): return sum(1 for c in lb["score_percentile_cuts"] if c < s)
def band_page(a):
    return pct(LBP, try_sim._band_score(LBP, a.get("name") or "", a.get("tagline") or "", (a.get("summary") or "") + " " + PHP.sub(" ", (a.get("page_excerpt") or "")[:1500]), a.get("topics") or []))
def band_paste(a, desc):
    return pct(LBH, try_sim._band_score(LBH, a.get("name") or "", a.get("tagline") or "", desc, a.get("topics") or []))
ok = [r for r in L.itertuples() if isinstance(K.get(f"p|{r.id}"), dict) and "read" in K[f"p|{r.id}"]]
F = pd.DataFrame([{"id": r.id, "rank": r.rank, "name": r.name, "tagline": r.tagline, "description": r.description, "day": r.day} for r in ok])
F["g"] = pd.qcut(F["rank"].rank(method="first"), 3, labels=False)
S = F.groupby("g", group_keys=False).apply(lambda g: g.sample(20, random_state=0)).reset_index(drop=True); print("sample", len(S), flush=True)
CAP = {}
_of = safe_fetch.fetch
async def _cf(url):
    r = await _of(url); CAP.setdefault("first", r); return r
safe_fetch.fetch = _cf
_gc = GC.gemini_chat
import contextvars
TEMP0V = contextvars.ContextVar("temp0", default=False)   # per asyncio task: concurrent launches are unaffected
async def _gc0(*a, **k):
    if TEMP0V.get(): k["temperature"] = 0.0
    return await _gc(*a, **k)
GC.gemini_chat = _gc0   # try_sim imports gemini_chat from this module at call time
PARA2 = "Rewrite this product description as exactly 2 plain sentences (what it is, who it is for). Use only these facts.\nName: {n}\nTagline: {t}\nSummary: {s}\nReturn JSON {{\"text\": \"...\"}}"
PARAL = ("Rewrite this product description as long marketing copy for a launch post (180-260 words, enthusiastic, benefit-led). Use ONLY these "
         "facts; do not invent features, numbers or customers.\nName: {n}\nTagline: {t}\nSummary: {s}\nStrengths: {st}\nPage excerpt: {e}\nReturn JSON {{\"text\": \"...\"}}")
JR = """List A and list B are short simulated user reactions to a product launch. For each item in B, does it raise the same specific point as
some item in A (same specific praise, concern or question, not merely the same broad area)? Return JSON {{"b_matches": [true/false per B item]}}
A:
{a}
B:
{b}"""
JT = """List A = themes real users raised in a product's launch comments. List B = simulated user reactions. For each item in B, does it raise
the same specific point as some item in A? Return JSON {{"b_matches": [true/false per B item]}}
A:
{a}
B:
{b}"""
def rtexts(rx): return [str(x.get("text") or x.get("comment") or x) for x in ((rx or {}).get("reactions") or [])][:6]
async def jmatch(JP, A, B):
    if not A or not B: return None
    bm = (await cj(JP.format(a=num(A), b=num(B)), tok=300)).get("b_matches"); bm = [tb(x) for x in bm] if isinstance(bm, list) else None
    return float(np.mean(bm)) if bm and len(bm) == len(B) else None

async def page_run(url, key, reactions=True):
    if key in C: return C[key]
    CAP.clear(); out = {}
    try:
        pg = await try_sim.step_page(url, "10.1.%d.%d" % (len(C) % 250, 7)); a = pg["analysis"]; out["read"] = {k: a.get(k) for k in ("name", "tagline", "summary", "topics", "strengths", "page_excerpt")}
        out["band"] = band_page(a)
        h = (CAP.get("first") or {}).get("html") or ""
        t = re.search(r"<title[^>]*>(.*?)</title>", h, re.S | re.I); md = re.search(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]*content=["\']([^"\']*)', h, re.I)
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S | re.I); clean = lambda x: _html.unescape(re.sub(r"<[^>]+>", " ", x.group(1))).strip() if x else ""
        out["hero"] = " ".join(z for z in (clean(t), clean(md), clean(h1)) if z)
        if reactions: out["reactions"] = rtexts(await try_sim.step_reactions(pg["token"]))
    except Exception as e: out["fail"] = str(e)[:160]
    C[key] = out; csave(); return out

async def paste_run(r, form, text, a0, key):
    if key in C: return C[key]
    out = {}
    try:
        text = " ".join(str(text).split())[:2000]
        if len(text) < 80: out["fail"] = "under 80 characters (step_text minimum)"; C[key] = out; csave(); return out
        nm = (r.name if form == "ph" else a0.get("name")) or "Product"; tg = ((r.tagline if form == "ph" else a0.get("tagline")) or "A new product")[:140]
        pg = await try_sim.step_text(nm, tg, text, "10.2.%d.%d" % (len(C) % 250, 9)); a = pg["analysis"]; out["band"] = band_paste(a, a.get("ph_description") or text)
        if form == "ph": out["reactions"] = rtexts(await try_sim.step_reactions(pg["token"]))
    except Exception as e: out["fail"] = str(e)[:160]
    C[key] = out; csave(); return out

async def per_launch(r, sem):
    async with sem:
        url = fix(U[r.id]); p = urlparse(url); root = f"https://{p.netloc}/"
        runs = [await page_run(url, f"run{k}|{r.id}", reactions=k < 2) for k in range(3)]
        tok_ = TEMP0V.set(True)
        try: t0 = [await page_run(url, f"t0_{k}|{r.id}", reactions=False) for k in range(2)]
        finally: TEMP0V.reset(tok_)
        rootr = await page_run(root, f"root|{r.id}", reactions=False) if root.rstrip("/") != url.rstrip("/") else {"same": True}
        a0 = (runs[0].get("read") or {})
        if a0:
            if f"para2|{r.id}" not in C:
                C[f"para2|{r.id}"] = (await cj(PARA2.format(n=a0.get("name"), t=a0.get("tagline"), s=a0.get("summary")), model="gemini-2.5-flash-lite", tok=300, temp=0.3)).get("text") or ""
            if f"paral|{r.id}" not in C:
                C[f"paral|{r.id}"] = (await cj(PARAL.format(n=a0.get("name"), t=a0.get("tagline"), s=a0.get("summary"), st="; ".join(a0.get("strengths") or []), e=(a0.get("page_excerpt") or "")[:1500]), model="gemini-2.5-flash-lite", tok=900, temp=0.3)).get("text") or ""
        pastes = {}
        for form, text in (("ph", r.description or ""), ("hero", runs[0].get("hero") or ""), ("para2", C.get(f"para2|{r.id}") or ""), ("paral", C.get(f"paral|{r.id}") or "")):
            pastes[form] = await paste_run(r, form, text, a0, f"paste_{form}|{r.id}")
        return {"runs": runs, "t0": t0, "root": rootr, "pastes": pastes}

async def main_s():
    sem = asyncio.Semaphore(4); return await asyncio.gather(*[per_launch(r, sem) for r in S.itertuples()])
OUTS = asyncio.run(main_s()); print("collected", flush=True)

# truth themes (identity-free comments, as in try_fixes) and judged comparisons
async def judged():
    sem = asyncio.Semaphore(6); perm = np.roll(np.arange(len(S)), 7)
    async def one(k, r):
        async with sem:
            o = OUTS[k]; m = OUTS[perm[k]]; key = f"judge|{r.id}"
            if key in C: return C[key]
            T = await cj(EX.format(c="\n".join(f"- {t[:400]}" for t in truth_c.get(r.id, [])[:40])), tok=1500) if len(truth_c.get(r.id, [])) >= 5 else {}
            themes = (T.get("critical") or [])[:6] + (T.get("questions") or [])[:6]
            r1, r2 = o["runs"][0].get("reactions"), o["runs"][1].get("reactions"); mm = m["runs"][0].get("reactions"); ph = o["pastes"]["ph"].get("reactions")
            res_ = {"agree_rerun": await jmatch(JR, r1, r2), "agree_mismatch": await jmatch(JR, r1, mm), "agree_page_vs_ph": await jmatch(JR, r1, ph),
                    "prec_page": await jmatch(JT, themes, r1), "prec_page_run2": await jmatch(JT, themes, r2), "prec_ph": await jmatch(JT, themes, ph), "n_themes": len(themes)}
            C[key] = res_; csave(); return res_
    return await asyncio.gather(*[one(k, r) for k, r in enumerate(S.itertuples())])
JD = asyncio.run(judged()); print("judged", flush=True)

# ranked concerns / questions reruns on the first 30 (2 reruns + mismatch)
async def rq():
    sem = asyncio.Semaphore(4)
    async def one(k, r):
        async with sem:
            key = f"rq|{r.id}"
            if key in C: return C[key]
            a = OUTS[k]["runs"][0].get("read")
            if not a: return None
            d = (a.get("summary") or "") + " " + (a.get("page_excerpt") or "")
            out = {}
            for kind in ("concerns", "questions"):
                l1, _ = await ranked(a["name"], a.get("tagline") or "", d, kind, r.day); l2, _ = await ranked(a["name"], a.get("tagline") or "", d, kind, r.day)
                out[kind] = [l1[:3], l2[:3]]
            C[key] = out; csave(); return out
    return await asyncio.gather(*[one(k, r) for k, r in enumerate(S.head(30).itertuples())])
RQ = asyncio.run(rq())
async def rq_overlap():
    sem = asyncio.Semaphore(6); perm = np.roll(np.arange(30), 7)
    async def one(k):
        async with sem:
            if RQ[k] is None or RQ[perm[k]] is None: return None
            key = f"rqj|{S.id.iat[k]}"
            if key in C: return C[key]
            o = {}
            for kind in ("concerns", "questions"):
                o[kind] = {"rerun": await jmatch(JR, RQ[k][kind][0], RQ[k][kind][1]), "mismatch": await jmatch(JR, RQ[k][kind][0], RQ[perm[k]][kind][0])}
            C[key] = o; csave(); return o
    return await asyncio.gather(*[one(k) for k in range(30)])
RQJ = asyncio.run(rq_overlap())

# ---------- metrics ----------
rk = S["rank"].values; n = len(S); rng = np.random.default_rng(0)
def col(f): return np.array([f(o) for o in OUTS], float)
g = lambda d, k="band": (d.get(k) if isinstance(d, dict) and k in d else np.nan)
B = {"run1": col(lambda o: g(o["runs"][0])), "run2": col(lambda o: g(o["runs"][1])), "run3": col(lambda o: g(o["runs"][2])),
     "t0_1": col(lambda o: g(o["t0"][0])), "t0_2": col(lambda o: g(o["t0"][1])), "root": col(lambda o: g(o["root"]) if not o["root"].get("same") else np.nan),
     "paste_ph": col(lambda o: g(o["pastes"]["ph"])), "paste_hero": col(lambda o: g(o["pastes"]["hero"])), "paste_para2": col(lambda o: g(o["pastes"]["para2"])), "paste_paral": col(lambda o: g(o["pastes"]["paral"]))}
B["mean3"] = np.nanmean(np.vstack([B["run1"], B["run2"], B["run3"]]), 0); B["mismatch"] = np.roll(B["run1"], 7)
dec = lambda x: np.minimum(9, x // 10)
def pair(a, b):
    m = ~np.isnan(a) & ~np.isnan(b)
    if m.sum() < 5: return {"n": int(m.sum())}
    d = np.abs(a[m] - b[m]); sp = spearmanr(a[m], b[m]).correlation
    bs = [spearmanr(a[m][j], b[m][j]).correlation for j in [rng.integers(0, m.sum(), m.sum()) for _ in range(1000)]]
    return {"n": int(m.sum()), "mean_abs_pct_diff": round(float(d.mean()), 1), "share_gt1_decile": round(float((np.abs(dec(a[m]) - dec(b[m])) > 1).mean()) * 100, 1),
            "spearman": [round(float(sp), 3), round(float(np.nanpercentile(bs, 2.5)), 3), round(float(np.nanpercentile(bs, 97.5)), 3)]}
res = {"design": __doc__.split("\n    python")[0], "n": n, "band_pairs": {}}
for a, b in (("run1", "run2"), ("run1", "run3"), ("run2", "run3"), ("t0_1", "t0_2"), ("run1", "root"), ("run1", "paste_ph"), ("run1", "paste_hero"),
             ("run1", "paste_para2"), ("run1", "paste_paral"), ("paste_ph", "paste_hero"), ("paste_ph", "paste_para2"), ("paste_ph", "paste_paral"), ("run1", "mismatch")):
    res["band_pairs"][f"{a} vs {b}"] = pair(B[a], B[b])
R3 = np.vstack([B["run1"], B["run2"], B["run3"]]); res["rerun_sd_pct"] = round(float(np.nanmean(np.nanstd(R3, 0, ddof=1))), 1)
res["t0_sd_pct"] = round(float(np.nanmean(np.nanstd(np.vstack([B["t0_1"], B["t0_2"]]), 0, ddof=1))), 1)
res["mismatch_sd_pct"] = round(float(np.nanmean(np.nanstd(np.vstack([B["run1"], B["mismatch"]]), 0, ddof=1))), 1)
# percentile -> rank movement (served page band deciles' median rank)
med = np.array([b_["daily_rank_p10_p50_p90"][1] for b_ in LBP["bands"]])
def rmove(a, b):
    m = ~np.isnan(a) & ~np.isnan(b); return round(float(np.median(np.abs(med[dec(a[m]).astype(int)] - med[dec(b[m]).astype(int)]))), 1), round(float(np.mean(np.abs(med[dec(a[m]).astype(int)] - med[dec(b[m]).astype(int)]))), 1)
res["median_rank_move (median, mean)"] = {"rerun": rmove(B["run1"], B["run2"]), "temp0": rmove(B["t0_1"], B["t0_2"]), "mismatch": rmove(B["run1"], B["mismatch"])}
def acc(x):
    m = ~np.isnan(x)
    if m.sum() < 10: return {"n": int(m.sum())}
    bs = [spearmanr(x[m][j], -rk[m][j]).correlation for j in [rng.integers(0, m.sum(), m.sum()) for _ in range(2000)]]
    return {"n": int(m.sum()), "spearman_-rank": [round(float(spearmanr(x[m], -rk[m]).correlation), 3), round(float(np.nanpercentile(bs, 2.5)), 3), round(float(np.nanpercentile(bs, 97.5)), 3)]}
res["accuracy_by_input"] = {k: acc(v) for k, v in B.items() if k != "mismatch"}
res["paste_failures"] = {f: int(sum(1 for o in OUTS if o["pastes"][f].get("fail"))) for f in ("ph", "hero", "para2", "paral")}
res["page_failures"] = int(sum(1 for o in OUTS if o["runs"][0].get("fail")))
mj = lambda k: [x[k] for x in JD if x and x.get(k) is not None]
def mb(v):
    v = np.array(v, float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]; return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
res["reactions"] = {k: mb(mj(k)) for k in ("agree_rerun", "agree_mismatch", "agree_page_vs_ph", "prec_page", "prec_page_run2", "prec_ph")}
res["ranked_overlap@3"] = {f"{kind} {w}": mb([x[kind][w] for x in RQJ if x and x[kind][w] is not None]) for kind in ("concerns", "questions") for w in ("rerun", "mismatch")}
json.dump(res, open(os.path.join(OUTD, "try_stability.json"), "w"), indent=1, default=float)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=float))
