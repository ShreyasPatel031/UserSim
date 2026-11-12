"""Do questions and concerns come from what the page does NOT say? (orchestrator 03:15Z Nov 12)
Same 300 post-cutoff launches as concerns_rank / questions_rank. Page text = PH description + held site text where available
(raw/sites_ph.jsonl visible text, else sites.jsonl HTML stripped; first 4,000 chars). 12 information needs:
  pricing, privacy, integrations, platforms, open_source, comparison, how_it_works, limits, team, roadmap, security, onboarding
Calls (gemini-2.5-flash-lite, temperature 0, JSON):
  PAGE    for each need: does the page answer it (true/false)
  ASKED   for each need: did any real non-team comment ask about it or raise it as a concern/request (true/false)
  ITEMS   the need (or "other") of each item in the RANKED concerns and RANKED questions lists (from concerns_rank/questions_rank)
(a) lift per need: P(asked | unanswered) / P(asked | answered), launch-bootstrap 95% CI.
(b) GAP list = unanswered needs ordered by the need's base rate of being asked among EARLIER launches of the sample (day < d;
    leave-one-out, falls back to the overall rate); GENERIC list = all needs by the same base rate; category-level precision@3
    and hit@3 (a listed need counts if real users asked about that need); RANKED lists scored at the same category level.
(c) RANKED lists re-ordered with the gap signal as a 4th vote (items whose need is unanswered move up), scored with the
    EXISTING per-item judge verdicts (theme level), paired vs the original order.
    python gap_eval.py <conc dir> <qrank dir> <cf dir> <launches dir> <aud dir (sites.jsonl, sites_ph.jsonl)> <out dir>
"""
import concurrent.futures as cf, glob, gzip, html, json, os, random, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd

CON, QR, CFD, LDIR, AUD, OUT = sys.argv[1:7]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
URL = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/gemini-2.5-flash-lite:generateContent"
_tok = {"t": "", "at": 0}; USD = {"usd": 0.0}
NEEDS = ["pricing", "privacy", "integrations", "platforms", "open_source", "comparison", "how_it_works", "limits", "team", "roadmap", "security", "onboarding"]
DESC = {"pricing": "pricing / free tier / cost", "privacy": "privacy / how user data is handled or stored", "integrations": "integrations with other tools / APIs",
        "platforms": "supported platforms (mobile app, OS, browser, desktop)", "open_source": "open source / self-hosting / repository",
        "comparison": "difference from named alternatives or incumbents", "how_it_works": "how it works technically / which AI model is used",
        "limits": "usage limits / quotas / performance limits", "team": "who is behind it / company / team background", "roadmap": "roadmap / upcoming features",
        "security": "security / compliance / certifications", "onboarding": "setup / onboarding / getting started"}


def token():
    if time.time() - _tok["at"] > 300:
        _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
    return _tok["t"]


def gem(prompt, maxtok=800):
    for i in range(6):
        try:
            req = urllib.request.Request(URL, json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": maxtok, "responseMimeType": "application/json"}}).encode(), {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
            j = json.load(urllib.request.urlopen(req, timeout=120)); u = j.get("usageMetadata", {})
            USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * 0.10 + u.get("candidatesTokenCount", 0) / 1e6 * 0.40
            return json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"]))
        except Exception as e:  # noqa: BLE001
            print("retry", i, str(e)[:100], flush=True); time.sleep(3 * (i + 1))
    return None


L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set()) for m, p in zip(L.makers, L.poster)]
L["topic"] = L.topics.map(lambda s: (json.loads(s) or ["none"])[0] if isinstance(s, str) and s.startswith("[") else "none")
bys = {s: r for s, r in zip(L.slug, L.itertuples())}; com = {}
for f in sorted(glob.glob(os.path.join(CFD, "page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        r = bys[p_["slug"]]
        def walk(n):
            u = ((n.get("user") or {}).get("username") or "").lower()
            t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", n.get("bodyHtml") or ""))).strip()
            if u not in r.team and len(t) > 15: com.setdefault(p_["slug"], {})[n.get("id")] = t
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
elig = [s for s, c in com.items() if len(c) >= 8 and "2026-08" <= bys[s].day <= "2026-10-31"]; random.Random(0).shuffle(elig); S = elig[:300]
want = {str(bys[s].id) for s in S}; site = {}
for line in open(os.path.join(AUD, "sites_ph.jsonl")):
    x = json.loads(line)
    if str(x.get("id")) in want and x.get("text") and str(x.get("parked")) != "True": site[str(x["id"])] = x["text"][:4000]
for line in open(os.path.join(AUD, "sites.jsonl")):
    x = json.loads(line)
    if str(x.get("id")) in want and str(x["id"]) not in site and x.get("html"):
        t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", x["html"]); site[str(x["id"])] = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))[:4000]
print("launches", len(S), "with site text", sum(str(bys[s].id) in site for s in S), flush=True)
needs_txt = "\n".join(f"- {k}: {v}" for k, v in DESC.items())
PAGE = """Below is everything a product's launch page and website say. For each information need, answer whether the page ANSWERS it
(states it clearly enough that a reader would not need to ask). Return JSON with exactly these keys, values true/false:
{keys}
Needs:
{needs}
Page:
{text}"""
ASK = """Below are real user comments on a product launch (makers' own comments removed). For each information need, answer whether
ANY comment asks about it or raises it as a concern or request. Return JSON with exactly these keys, values true/false:
{keys}
Needs:
{needs}
Comments:
{c}"""
ITEMS = """Classify each item by the information need it is about (one of: {keys}, other).
Return JSON {{"needs": ["...", ...]}} in order.
Needs:
{needs}
Items:
{items}"""
CN = json.load(open(os.path.join(CON, "cache.json"))); CQ = json.load(open(os.path.join(QR, "cache.json")))
cache_f = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(key, fn):
    if key not in K: K[key] = fn()
    return K[key]
def page(s):
    r = bys[s]; t = f"{r.name}. {r.tagline}. {r.description or ''}\n{site.get(str(r.id), '')}"[:5500]
    return gem(PAGE.format(keys=", ".join(NEEDS), needs=needs_txt, text=t)) or {}
def asked(s):
    return gem(ASK.format(keys=", ".join(NEEDS), needs=needs_txt, c="\n".join(f"- {t[:350]}" for t in list(com[s].values())[:40]))) or {}
def items(s, which):
    lst = (CN if which == "c" else CQ).get(f"{'ranked' if which == 'c' else 'qranked'}|{s}") or []
    if not lst: return []
    a = gem(ITEMS.format(keys=", ".join(NEEDS), needs=needs_txt, items="\n".join(f"{k+1}. {t[:300]}" for k, t in enumerate(lst)))) or {}
    n = a.get("needs") or []; return n if len(n) == len(lst) else ["other"] * len(lst)
jobs = [(s, k) for s in S for k in ("page", "asked", "ic", "iq")]
def do(j):
    s, k = j
    return run(f"{k}|{s}", {"page": lambda: page(s), "asked": lambda: asked(s), "ic": lambda: items(s, "c"), "iq": lambda: items(s, "q")}[k])
with cf.ThreadPoolExecutor(10) as ex: list(ex.map(do, jobs))
json.dump(K, open(cache_f, "w")); print("usd", round(USD["usd"], 3), flush=True)
ans = pd.DataFrame([{n: bool((K[f"page|{s}"] or {}).get(n, False)) for n in NEEDS} for s in S], index=S)
ask = pd.DataFrame([{n: bool((K[f"asked|{s}"] or {}).get(n, False)) for n in NEEDS} for s in S], index=S)
day = pd.Series({s: bys[s].day for s in S})


def boot(fn, B=2000):
    vals = []
    for _ in range(B):
        ix = rng.integers(0, len(S), len(S)); vals.append(fn(np.array(S)[ix]))
    vals = np.array(vals, float); return [round(float(np.nanpercentile(vals, 2.5)), 3), round(float(np.nanpercentile(vals, 97.5)), 3)]


res = {"design": __doc__.split("\n    python")[0], "launches": len(S), "with_site_text": int(sum(str(bys[s].id) in site for s in S)),
       "share_answered_on_page": ans.mean().round(3).to_dict(), "share_asked": ask.mean().round(3).to_dict(), "lift": {}}
for n in NEEDS:
    def lift(ss, n=n):
        a, k = ans.loc[ss, n], ask.loc[ss, n]
        p0, p1 = k[~a].mean(), k[a].mean()
        return p0 / p1 if p1 > 0 else np.nan
    res["lift"][n] = {"P(asked|unanswered)": round(float(ask[n][~ans[n]].mean()), 3) if (~ans[n]).any() else None,
                      "P(asked|answered)": round(float(ask[n][ans[n]].mean()), 3) if ans[n].any() else None,
                      "n_unanswered": int((~ans[n]).sum()), "lift": round(float(lift(S)), 2) if not np.isnan(lift(S)) else None, "lift_ci": boot(lift)}
# (b) category-level lists
def base_rates(s):
    prev = [o for o in S if day[o] < day[s] and o != s]
    return (ask.loc[prev].mean() if len(prev) >= 30 else ask.drop(index=s).mean())
rows = []
for s in S:
    br = base_rates(s)
    gap = [n for n in br.sort_values(ascending=False).index if not ans.loc[s, n]]
    gen = list(br.sort_values(ascending=False).index)
    rc = [x for x in (K.get(f"ic|{s}") or []) if x in NEEDS]; rq = [x for x in (K.get(f"iq|{s}") or []) if x in NEEDS]
    dedup = lambda l: list(dict.fromkeys(l))
    for nm, lst in (("GAP", gap), ("GENERIC", gen), ("RANKED_concerns", dedup(rc)), ("RANKED_questions", dedup(rq))):
        top = lst[:3]
        rows.append({"s": s, "list": nm, "p3": np.mean([ask.loc[s, n] for n in top]) if top else np.nan, "hit3": float(any(ask.loc[s, n] for n in top)) if top else np.nan, "len": len(top)})
D = pd.DataFrame(rows); W = D.pivot_table(index="s", columns="list", values=["p3", "hit3"])
def mb(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]
res["category_level"] = {nm: {m: mb(D[D.list == nm][m]) for m in ("p3", "hit3")} for nm in ("GAP", "GENERIC", "RANKED_concerns", "RANKED_questions")}
res["category_level_paired"] = {f"GAP - {b}": {m: mb(W[(m, "GAP")] - W[(m, b)]) for m in ("p3", "hit3")} for b in ("GENERIC", "RANKED_concerns", "RANKED_questions")}
# (c) re-rank RANKED lists with the gap vote using the existing per-item verdicts
rr = []
for which, jk, ik in (("concerns", "j|RANKED|", "ic|"), ("questions", "qj|RANKED|", "iq|")):
    src = CN if which == "concerns" else CQ
    for s in S:
        v = src.get(f"{jk}{s}"); cats = K.get(f"{ik}{s}") or []
        if not v or len(cats) != len(v): continue
        sc = [(5 - i) / 5 + (0.5 if (c in NEEDS and not ans.loc[s, c]) else 0.0) for i, c in enumerate(cats)]
        order = list(np.argsort(-np.array(sc), kind="stable"))
        o, n_ = np.array(v, float), np.array(v, float)[order]
        rr.append({"which": which, "s": s, "p3_orig": o[:3].mean(), "p3_gap": n_[:3].mean(), "hit3_orig": float(o[:3].any()), "hit3_gap": float(n_[:3].any())})
R = pd.DataFrame(rr)
res["rerank_with_gap_vote"] = {w: {"p3_orig": mb(g.p3_orig), "p3_gap": mb(g.p3_gap), "p3 diff (paired)": mb(g.p3_gap - g.p3_orig),
                                   "hit3_orig": mb(g.hit3_orig), "hit3_gap": mb(g.hit3_gap), "hit3 diff (paired)": mb(g.hit3_gap - g.hit3_orig)} for w, g in R.groupby("which")}
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "gap_eval.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
