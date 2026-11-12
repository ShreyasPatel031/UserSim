"""Try-a-URL end to end through the website's own code (orchestrator 09:30Z Nov 12). Library calls into origin/claude/ph-website
mvp/ph_site/try_sim.py (step_page -> safe_fetch.check_url/fetch_product + READ_PROMPT on gemini-2.5-flash-lite; step_reactions ->
person_e5 member types + reactions_retrieval_v1 grounding + REACT_PROMPT on gemini-2.5-flash at 0.3; step_launch -> launch_band.json
product-only band), with TRY_SIGNING_KEY a local dummy and TRY_LOCAL_LIMITS=1 (in-memory run store / rate limits, one fake IP per
launch). Nothing goes through the public site.
Launches: ranked launches of Oct 27 - Nov 10 2026 (after every training set; Oct 25-26 have no stored comment text) with a resolved
product URL (sites.jsonl, live) and >= 5 identity-free truth comments, stratified by final rank group. Each product site is fetched
ONCE by the site's safe_fetch; any refusal / error / "no readable text" / page-judge "problem" counts as a skip (the skip reason is
recorded).
Paired arm: the same launch through the same step_reactions / step_launch, with the analysis built from the PH name / tagline /
description / topics instead of the page read (what our earlier harness measured).
Truth: PH API comment snapshots (raw/ph_at_launch/<day>/api_comments, union of snapshots, deduped by comment id); identity-free
team rule: the earliest top-level comment's author is the maker - all their comments dropped (the hunter cannot be matched by id
here; noted). Extraction and judges as ceiling.py / truth_fix.py (themes / critical / questions; blinded judges).
Metrics: reactions theme recall / precision, critical recall, question recall; page "doubts" as a concern list (p@3 vs critical
truth; the site has no ranked concerns or questions list); band coverage of the true daily rank and decile; latency per step;
Gemini cost per request (token estimate = characters / 4 at list prices); failure modes.
    python try_e2e.py <ph-website worktree> <scratchpad> <out dir> [N]
"""
import asyncio, glob, json, os, random, re, sys, time, html as _html
import numpy as np, pandas as pd

WT, SP, OUT = sys.argv[1:4]; N = int(sys.argv[4]) if len(sys.argv) > 4 else 60; os.makedirs(OUT, exist_ok=True)
os.environ["TRY_SIGNING_KEY"] = "local-dummy-key-for-offline-eval-0123456789"; os.environ["TRY_LOCAL_LIMITS"] = "1"; os.environ.setdefault("TRY_GLOBAL_DAY", "5000")
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(SP, "gcp_key.json")); os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox")
sys.path[:0] = [WT, os.path.join(WT, "src")]
from mvp.ph_site import try_sim  # noqa: E402
from capability import gemini_config as GC  # noqa: E402
rng = np.random.default_rng(0)
USE = {"chars_in": {}, "chars_out": {}}
_orig = GC.gemini_chat


async def counted(messages, model=None, **kw):                     # wrap to estimate cost per model
    t = await _orig(messages, model=model, **kw)
    m = model or "default"; USE["chars_in"][m] = USE["chars_in"].get(m, 0) + sum(len(x.get("content", "")) for x in messages)
    USE["chars_out"][m] = USE["chars_out"].get(m, 0) + len(t or ""); return t
GC.gemini_chat = counted
PRICE = {"gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-flash": (0.30, 2.50)}

# ---------- launches, urls, truth ----------
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & (L.day >= "2026-10-27") & (L.day <= "2026-11-10")].copy(); L["id"] = L.id.astype(str); L["rank"] = L.daily_rank.astype(float)
U = json.load(open(os.path.join(SP, "try_e2e/urls.json")))   # at-launch primary_link (3 days) else the first non-PH link in the maker's first comment
C = {}
for f in glob.glob(os.path.join(SP, "try_e2e/apic/*/*.jsonl")):
    for l in open(f):
        x = json.loads(l); C[x["comment_id"]] = x
clean = lambda t: re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
bypost = {}
for x in C.values(): bypost.setdefault(str(x["post_id"]), []).append(x)
truth_c = {}
for p, cs in bypost.items():
    tops = sorted([(c["createdAt"], c["commenter_user_id"]) for c in cs if not c.get("parentId")])
    maker = tops[0][1] if tops else None
    truth_c[p] = [clean(c["body"]) for c in sorted(cs, key=lambda c: c["createdAt"]) if c["commenter_user_id"] != maker and len(clean(c["body"])) > 15]
L["n_truth"] = L.id.map(lambda i: len(truth_c.get(i, []))); L["url"] = L.id.map(U)
E = L[L.url.notna() & (L.n_truth >= 5)].copy()
E["grp"] = np.where(E["rank"] == 1, "1", np.where(E["rank"] <= 3, "2-3", np.where(E["rank"] <= 10, "4-10", "11+")))
quota = {"1": 12, "2-3": 14, "4-10": 18, "11+": 16}
S = pd.concat([g.sample(min(len(g), quota[k]), random_state=0) for k, g in E.groupby("grp")])
if len(S) < N:
    S = pd.concat([S, E.drop(S.index).sample(min(N - len(S), len(E) - len(S)), random_state=0)])
S = S.head(N).reset_index(drop=True)
print("eligible", len(E), "by group", E.grp.value_counts().to_dict(), "sample", len(S), S.grp.value_counts().to_dict(), flush=True)

# ---------- truth + judges (same prompts as ceiling.py) ----------
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
tb = lambda x: x if isinstance(x, bool) else str(x).strip().lower() in ("true", "yes", "1")
num = lambda l: "\n".join(f"{k+1}. {t}" for k, t in enumerate(l))
cache_f = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f)) if os.path.exists(cache_f) else {}


async def gj(prompt, tok=1500):
    try: return GC.extract_json(await GC.gemini_chat([{"role": "user", "content": prompt}], model="gemini-2.5-flash", temperature=0.0, max_retries=3, max_output_tokens=tok)) or {}
    except Exception: return {}  # noqa: BLE001


async def judge_rp(real, cand):
    if not real or not cand: return None
    a = await gj(JUDGE.format(a=num(real), b=num(cand)), 800)
    ac, bp = [tb(x) for x in a.get("a_covered", [])], [tb(x) for x in a.get("b_present", [])]
    return (float(np.mean(ac)), float(np.mean(bp))) if len(ac) == len(real) and len(bp) == len(cand) else None


async def judge_p3(real, cand):
    if not real or not cand: return None
    bm = (await gj(JC.format(a=num(real), b=num(cand[:3])), 300)).get("b_matches")
    bm = [tb(x) for x in bm] if isinstance(bm, list) else None
    return (float(np.mean(bm)), float(any(bm))) if bm and len(bm) == len(cand[:3]) else None


def rtexts(r): return [f"{x.get('comment', '')} ({x.get('why', '')})" for x in (r or {}).get("reactions", [])]
vocab = set(try_sim.index()["meta"]["vocab"])


async def one(k, r, sem):
    async with sem:
        out = {"id": r.id, "day": r.day, "rank": r["rank"], "grp": r.grp, "url_domain": re.sub(r"^www\.", "", re.sub(r"^https?://", "", r.url).split("/")[0])}
        key = f"run|{r.id}"
        if key in K: out.update(K[key]); return out
        ip = f"10.9.{k // 250}.{k % 250}"
        if r.url.startswith("http://"):   # our container runs safe_fetch in proxy mode, which only allows https; production fetches http directly
            r = r.copy(); r["url"] = "https://" + r.url[len("http://"):]; out["http_rewritten"] = True
        # site path
        t0 = time.time()
        try:
            pg = await try_sim.step_page(r.url, ip); t1 = time.time()
            tok = pg["token"]; out["page"] = pg["analysis"]; out["lat_page"] = t1 - t0
            rx = await try_sim.step_reactions(tok); t2 = time.time(); out["lat_react"] = t2 - t1; out["site_react"] = rtexts(rx); out["site_grounded"] = rx.get("grounded")
            ln = try_sim.step_launch(tok); out["lat_launch"] = time.time() - t2; out["site_band"] = {k2: ln[k2] for k2 in ("percentile", "decile", "rank_band")}
        except Exception as e:  # noqa: BLE001
            out["skip"] = f"{type(e).__name__}: {str(e)[:160]}"; out["lat_fail"] = time.time() - t0
        # PH-description path (same reaction/launch code)
        try:
            tp = [t for t in (json.loads(r.topics) if isinstance(r.topics, str) and r.topics.startswith("[") else []) if t in vocab][:4] or ["Productivity"]
            a = {"name": r["name"], "tagline": r.tagline or "", "summary": (r.description or "")[:400], "topics": tp, "audience": "", "pricing": "unknown",
                 "strengths": [], "doubts": [], "clarity": None, "url": r.url, "page_excerpt": (r.description or "")[:2500]}
            tok2 = try_sim.new_run(a); t3 = time.time(); rx2 = await try_sim.step_reactions(tok2); out["lat_react_ph"] = time.time() - t3
            out["ph_react"] = rtexts(rx2); ln2 = try_sim.step_launch(tok2); out["ph_band"] = {k2: ln2[k2] for k2 in ("percentile", "decile", "rank_band")}
        except Exception as e:  # noqa: BLE001
            out["ph_err"] = f"{type(e).__name__}: {str(e)[:160]}"
        # truth + judges
        T = await gj(EX.format(c="\n".join(f"- {t[:400]}" for t in truth_c[r.id][:40])), 2000)
        tt = [str(x.get("theme")) for x in (T.get("themes") or []) if isinstance(x, dict) and x.get("theme")][:8]; tc = (T.get("critical") or [])[:6]; tq = (T.get("questions") or [])[:6]
        out["truth_n"] = len(truth_c[r.id])
        for arm in ("site", "ph"):
            rr = out.get(f"{arm}_react")
            if rr:
                out[f"{arm}_rp"] = await judge_rp(tt, rr); out[f"{arm}_cr"] = await judge_rp(tc, rr); out[f"{arm}_qr"] = await judge_rp(tq, rr)
        if out.get("page"): out["site_doubts_p3"] = await judge_p3(tc, out["page"].get("doubts") or [])
        K[key] = {k2: v for k2, v in out.items() if k2 not in ("id", "day", "rank", "grp", "url_domain")}
        json.dump(K, open(cache_f, "w"))
        print(k, r.grp, "skip" if "skip" in out else "ok", out.get("skip", "")[:80], flush=True)
        return out


async def main():
    sem = asyncio.Semaphore(5)
    return await asyncio.gather(*[one(k, r, sem) for k, r in S.iterrows()])
R = asyncio.run(main())
json.dump(K, open(cache_f, "w"))
D = pd.DataFrame(R)


def mb(v, B=4000, scale=100):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * scale, 1), round(float(np.percentile(bs, 2.5)) * scale, 1), round(float(np.percentile(bs, 97.5)) * scale, 1), int(len(v))]
g = lambda col, j: np.array([(x[j] if isinstance(x, (list, tuple)) and x else np.nan) for x in D.get(col, pd.Series([None] * len(D)))], float)
ok = D.skip.isna() if "skip" in D else pd.Series(True, index=D.index)
res = {"design": __doc__.split("\n    python")[0], "sampled": len(D), "by_group": D.grp.value_counts().to_dict(),
       "skip_rate": round(float((~ok).mean()), 3), "skip_by_group": (~ok).groupby(D.grp).mean().round(3).to_dict(),
       "skip_reasons": D.loc[~ok, "skip"].str.split(":").str[0].value_counts().to_dict() if (~ok).any() else {},
       "skip_examples": D.loc[~ok, ["url_domain", "skip"]].head(25).values.tolist() if (~ok).any() else [], "quality": {}}
for m, col, j in (("theme_recall", "rp", 0), ("theme_precision", "rp", 1), ("critical_recall", "cr", 0), ("question_recall", "qr", 0)):
    s, p = g(f"site_{col}", j), g(f"ph_{col}", j)
    res["quality"][m] = {"site page read (fetched ok)": mb(s), "PH description (same launches)": mb(np.where(np.isnan(s), np.nan, p)),
                         "site - PH (paired)": mb(s - p), "PH description (all sampled)": mb(p)}
res["quality"]["page doubts as concerns p@3"] = mb(g("site_doubts_p3", 0)); res["quality"]["page doubts hit@3"] = mb(g("site_doubts_p3", 1))


def cov(col):
    c = []
    for b, rk in zip(D.get(col, []), D["rank"]):
        if isinstance(b, dict): lo, hi = b["rank_band"]["likely"]; c.append(float(lo <= rk <= hi))
    return mb(c)
res["band"] = {"coverage of true rank, site page": cov("site_band"), "coverage, PH description": cov("ph_band"),
               "spearman(site percentile, -rank)": None, "spearman(PH percentile, -rank)": None}
from scipy.stats import spearmanr  # noqa: E402
for col, lab in (("site_band", "spearman(site percentile, -rank)"), ("ph_band", "spearman(PH percentile, -rank)")):
    xs = [(b["percentile"], -rk) for b, rk in zip(D.get(col, []), D["rank"]) if isinstance(b, dict)]
    if len(xs) > 5: res["band"][lab] = round(float(spearmanr(*zip(*xs)).correlation), 3)
xs = [(a["percentile"], b["percentile"]) for a, b in zip(D.get("site_band", []), D.get("ph_band", [])) if isinstance(a, dict) and isinstance(b, dict)]
res["band"]["spearman(site percentile, PH percentile)"] = round(float(spearmanr(*zip(*xs)).correlation), 3) if len(xs) > 5 else None
lat = {c: [round(float(np.nanmedian(D[c])), 1), round(float(np.nanpercentile(D[c], 90)), 1)] for c in ("lat_page", "lat_react", "lat_launch", "lat_react_ph") if c in D}
res["latency_s_median_p90"] = lat
usd = sum(USE["chars_in"].get(m, 0) / 4 / 1e6 * PRICE.get(m, (0.3, 2.5))[0] + USE["chars_out"].get(m, 0) / 4 / 1e6 * PRICE.get(m, (0.3, 2.5))[1] for m in USE["chars_in"])
res["gemini_usd_estimate_total"] = round(usd, 3)
pr = USE["chars_in"].get("gemini-2.5-flash-lite", 0) / 4 / 1e6 * 0.10 + USE["chars_out"].get("gemini-2.5-flash-lite", 0) / 4 / 1e6 * 0.40
res["page_read_usd_per_request_estimate"] = round(pr / max(1, int(ok.sum() + (~ok).sum())), 5)
res["grounded_share"] = round(float(pd.Series(D.get("site_grounded")).dropna().astype(float).mean()), 3) if "site_grounded" in D else None
res["page_clarity_mean"] = round(float(np.nanmean([p.get("clarity") or np.nan for p in D.get("page", []) if isinstance(p, dict)])), 2) if "page" in D else None
json.dump(res, open(os.path.join(OUT, "try_e2e.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
