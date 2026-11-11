"""Raise the "what users will say" metric (orchestrator 02:00Z Nov 12). Same 300 launches, truth themes, blinded judge and
recall/precision definitions as reactions_eval.py (site mode); every variant is paired by launch against the site's current
pipeline (V0 = REACT_PROMPT verbatim, flash-lite, temperature 0.7, 6 comments, E5 member types + 2 contrast types).
Variants
  R{k}      retrieval grounding, k = 3/5/10: the k most similar launches dated strictly BEFORE the target (gemini-embedding of
            name + tagline + description; excluded: shared real maker/poster, same product family = same slug stem or the same
            name), their real non-team comments condensed to themes by flash-lite (themes only, never verbatim comments) and
            added to the prompt as "users of similar past products raised: ...".
  N10/N15   10 / 15 comments (member types extended with generic PH member types).
  TWO       two passes: (1) list expected themes by type (praise, objection, question, feature request, comparison),
            (2) write the comments from those themes.
  FLASH3    gemini-2.5-flash, temperature 0.3.   LITE3: flash-lite, temperature 0.3.
  SITE      the product's own site text (sites.jsonl, live fetch) as the page excerpt where held, else the PH description.
  BEST      the best retrieval k combined with the best of the other levers (chosen on the primary run, reported as such).
Cross-judge: V0 and BEST on 100 launches with a second, differently worded judge (per real theme: 0 = not addressed,
1 = same area, 2 = same specific point; covered = 2).
    python reactions_v2.py <react_site dir (cache_site.json)> <cf dir> <launches dir> <sites.jsonl> <bundle.npz> <try_sim.py> <out dir> [variants]
"""
import ast, concurrent.futures as cf, glob, gzip, html, json, os, random, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd

RS, CFD, LDIR, SITES, BUNDLE, TRY, OUT = sys.argv[1:8]; os.makedirs(OUT, exist_ok=True)
ONLY = sys.argv[8].split(",") if len(sys.argv) > 8 else None
rng = np.random.default_rng(0)
BASE = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/{m}:generateContent"
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-flash-lite": (0.10, 0.40)}
_tok = {"t": "", "at": 0}; USD = {"usd": 0.0}; LAT = {}


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
            print("retry", i, str(e)[:120], flush=True); time.sleep(4 * (i + 1))
    return None


def gem(prompt, model="gemini-2.5-flash", temp=0.0, maxtok=2500, tag=None):
    t0 = time.time()
    j = post(BASE.format(m=model), {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                                    "generationConfig": {"temperature": temp, "maxOutputTokens": maxtok, "responseMimeType": "application/json",
                                                         "thinkingConfig": {"thinkingBudget": 0}}})
    if tag: LAT.setdefault(tag, []).append(time.time() - t0)
    if not j: return None
    u = j.get("usageMetadata", {}); p = PRICE[model]
    USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * p[0] + u.get("candidatesTokenCount", 0) / 1e6 * p[1]
    try: return json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"]))
    except Exception: return None


def embed(texts):
    out = []
    for i in range(0, len(texts), 200):
        j = post(EMB, {"instances": [{"content": t[:2000], "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]], "parameters": {"outputDimensionality": 256}})
        out.append(np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32))
    E = np.vstack(out); return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


# ---------- data (same parsing as reactions_eval.py)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set())
             for m, p in zip(L.makers, L.poster)]
L["topic"] = L.topics.map(lambda s: (json.loads(s) or ["none"])[0] if isinstance(s, str) and s.startswith("[") else "none")
bys = {s: r for s, r in zip(L.slug, L.itertuples())}
com = {}
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
elig = [s for s, c in com.items() if len(c) >= 8 and "2026-08" <= bys[s].day <= "2026-10-31"]
random.Random(0).shuffle(elig); S = elig[:300]
C0 = json.load(open(os.path.join(RS, "cache_site.json")))
truth = {s: C0[f"truth|{s}"] for s in S if C0.get(f"truth|{s}")}
v0 = {s: C0.get(f"persona|{s}") for s in S}
print("sample", len(S), "truth", len(truth), flush=True)
cache_f = os.path.join(OUT, "cache_v2.json"); C = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(key, fn):
    if key not in C: C[key] = fn()
    return C[key]

# site texts
site_txt = {}
want = {str(bys[s].id) for s in S}
for line in open(SITES):
    x = json.loads(line)
    if str(x.get("id")) in want and x.get("html"):
        t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", x["html"])
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()
        if len(t) > 200: site_txt[str(x["id"])] = t[:2500]
print("site text held for", sum(str(bys[s].id) in site_txt for s in S), "of", len(S), flush=True)

# retrieval pool: launches with >= 5 non-team comments in the dump
pool = [s for s, c in com.items() if len(c) >= 5]
pf = os.path.join(OUT, "pool_emb.npy")
ptxt = [f"{bys[s].name}. {bys[s].tagline}. {(bys[s].description or '')[:800]}" for s in pool]
PE = np.load(pf) if os.path.exists(pf) and np.load(pf).shape[0] == len(pool) else embed(ptxt); np.save(pf, PE)
ppos = {s: i for i, s in enumerate(pool)}
stem = lambda s: re.sub(r"-\d+$", "", s)


def neighbours(s, k):
    r = bys[s]; q = PE[ppos[s]] if s in ppos else embed([f"{r.name}. {r.tagline}. {(r.description or '')[:800]}"])[0]
    sims = PE @ q; out = []
    for j in np.argsort(-sims):
        o = pool[j]; ro = bys[o]
        if ro.day >= r.day or stem(o) == stem(s) or str(ro.name).lower() == str(r.name).lower() or (ro.team & r.team): continue
        out.append(o)
        if len(out) == k: break
    return out


NT = """Below are real user comments on a past product launch. Summarise the distinct points users raised as short themes
(praise, objection, question, feature request, comparison). Do not quote; paraphrase; no names or handles.
Return JSON {{"themes": ["<type>: <theme>", ...]}} with at most 6 themes.
Comments:
{c}"""
def nb_themes(o):
    return run(f"nbth|{o}", lambda: ((gem(NT.format(c="\n".join(f"- {t[:300]}" for t in list(com[o].values())[:30])), "gemini-2.5-flash-lite", 0.0, 800) or {}).get("themes") or [])[:6])


SITE_PROMPT = next(n.value.value for n in ast.parse(open(TRY).read()).body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "REACT_PROMPT")
types_re = re.compile(r"User [A-H]:[^\n]*")
def site_types(s):                                   # the member types the site used for V0 are reconstructed from the V0 run
    return C0.get(f"types|{s}")


# E5 scorer member types (same as reactions_eval site mode)
BZ = np.load(BUNDLE); IE = BZ["item_emb"].astype(np.float32); PTR, IDX = BZ["person_ptr"], BZ["person_items"]
TR = {k: BZ[k] for k in ("tree_feat", "tree_thr", "tree_left", "tree_right", "tree_value", "tree_roots")}; RN = list(BZ["role_names"]); NU = BZ["n_uses"]
def member_types(s, n4=4):
    r = bys[s]; q = embed([f"{r.name}. {r.tagline}. {(r.description or '')[:1100]}"])[0]
    v = IE @ q; F = np.zeros((len(PTR) - 1, 5), np.float32); ok = np.diff(PTR) > 0
    for j in np.flatnonzero(ok):
        x = v[IDX[PTR[j]:PTR[j + 1]]]; xs = np.sort(x); F[j] = [xs[-1], xs[-5:].mean(), x.mean(), (x > float(BZ["hi"])).mean(), np.log1p(len(x))]
    sc = np.zeros(len(F))
    for rt in TR["tree_roots"]:
        n = np.full(len(F), rt)
        while True:
            f = TR["tree_feat"][n]; leaf = f < 0
            if leaf.all(): break
            n = np.where(leaf, n, np.where(F[np.arange(len(F)), np.maximum(f, 0)] <= TR["tree_thr"][n], TR["tree_left"][n], TR["tree_right"][n]))
        sc += TR["tree_value"][n]
    sc[~ok] = -1e9; out, seen = [], set()
    tl = json.loads(r.topics) if isinstance(r.topics, str) and r.topics.startswith("[") else []
    for j in np.argsort(-(sc - BZ["pct99_tree"])):
        ro = tuple(RN[k] for k in np.flatnonzero(BZ["roles"][j])) or ("member",)
        ti = "1-3 tools" if NU[j] <= 3 else ("4-10 tools" if NU[j] <= 10 else "11+ tools")
        if (ro, ti) in seen: continue
        seen.add((ro, ti)); out.append(f"{' / '.join(ro)}, {ti}, interested in {', '.join(tl[:2]) or 'this category'}")
        if len(out) == n4: break
    return out


CONTRAST = ["heavy PH voter who comments often and sees dozens of similar launches a week", "maker from an unrelated category, browsing the day's launches"]
GENERIC_EXTRA = ["skeptical engineer who checks pricing, privacy and how it works under the hood", "early adopter who already uses a competing tool",
                 "busy founder deciding whether it is worth switching", "designer who notices the UI and onboarding first", "PH regular who asks the maker a direct question",
                 "user in a small team on a tight budget", "power user who wants integrations and an API", "first-time PH visitor from the product's target audience",
                 "data/AI practitioner curious about the model and accuracy"]


def build_types(s, n):
    base = run(f"mt|{s}", lambda: member_types(s)) + CONTRAST
    t = (base + GENERIC_EXTRA)[:n]
    return [f"User {chr(65 + i)}: {x}" if i < 26 else x for i, x in enumerate(t)]


def prompt_for(s, n=6, k=0, site=False, two=None):
    r = bys[s]; desc = (r.description or "")[:1500]
    excerpt = site_txt.get(str(r.id), desc) if site else desc
    p = SITE_PROMPT.format(name=r.name, tagline=r.tagline or "", summary=desc, pricing="unknown", strengths="", doubts="",
                           excerpt=excerpt[:2500], types="\n".join(build_types(s, n)))
    if k:
        nb = neighbours(s, k); th = [t for o in nb for t in nb_themes(o)]
        p += "\n\nFor grounding: users of similar past Product Hunt products raised these points (other products, not this one; reuse only what plausibly applies here):\n" + "\n".join(f"- {t}" for t in th[:6 * k])
    if two:
        p += "\n\nFirst-pass expected themes for THIS product (cover them where they fit the member type):\n" + "\n".join(f"- {t}" for t in two)
    return p


TWO1 = """Product: {name} - {tagline}
Description: {desc}
List the specific themes Product Hunt users are most likely to raise in launch comments, by type: praise, objection, question,
feature request, comparison to named alternatives. Be specific to this product; do not invent features.
Return JSON {{"themes": ["<type>: <theme>", ...]}} with 8 themes."""


def gen(s, v):
    cfg = VAR[v]; model, temp, n, k = cfg.get("model", "gemini-2.5-flash-lite"), cfg.get("temp", 0.7), cfg.get("n", 6), cfg.get("k", 0)
    two = None
    if cfg.get("two"):
        r = bys[s]; two = ((gem(TWO1.format(name=r.name, tagline=r.tagline, desc=(r.description or "")[:1500]), model, temp, 800, tag=v + "_p1") or {}).get("themes") or [])[:8]
    a = gem(prompt_for(s, n, k, cfg.get("site", False), two), model, temp, 4000, tag=v)
    return [f"{x.get('comment', '')} ({x.get('why', '')})" for x in ((a or {}).get("reactions") or []) if isinstance(x, dict)][:n]


VAR = {"R3": {"k": 3}, "R5": {"k": 5}, "R10": {"k": 10}, "N10": {"n": 10}, "N15": {"n": 15}, "TWO": {"two": True},
       "FLASH3": {"model": "gemini-2.5-flash", "temp": 0.3}, "LITE3": {"temp": 0.3}, "SITE": {"site": True}}
if os.environ.get("BEST"): VAR["BEST"] = json.loads(os.environ["BEST"])
todo = [v for v in VAR if not ONLY or v in ONLY]

JUDGE = """List A = themes real users raised about a product. List B = candidate themes.
For each item in A, say whether some item in B substantially covers the same point (same concern/praise/question/request,
not merely the same broad area). For each item in B, say whether it substantially matches some item in A.
Return JSON {{"a_covered": [true/false per A item], "b_present": [true/false per B item]}}.
A:
{a}
B:
{b}"""
JUDGE2 = """You are auditing a forecast of launch-day user feedback.
REAL: points actual users made.
FORECAST: points a model predicted, in no particular order.
For every REAL point give 0 (nothing in FORECAST addresses it), 1 (FORECAST touches the same general area only) or 2 (FORECAST
makes essentially the same specific point). For every FORECAST point give true if it corresponds to a specific REAL point.
Return JSON {{"real_scores": [0|1|2 ...], "forecast_hits": [true|false ...]}}.
REAL:
{a}
FORECAST:
{b}"""


def judge(real, cand, second=False):
    A = "\n".join(f"{i+1}. {t['theme']}" for i, t in enumerate(real)); B = "\n".join(f"{i+1}. {t}" for i, t in enumerate(cand))
    a = gem((JUDGE2 if second else JUDGE).format(a=A, b=B), "gemini-2.5-flash", 0.0, 800)
    if not isinstance(a, dict): return None
    if second:
        rs, fh = a.get("real_scores", []), a.get("forecast_hits", [])
        if len(rs) != len(real) or len(fh) != len(cand): return None
        return [int(x) >= 2 for x in rs], [bool(x) for x in fh]
    ac, bp = a.get("a_covered", []), a.get("b_present", [])
    if len(ac) != len(real) or len(bp) != len(cand): return None
    return [bool(x) for x in ac], [bool(x) for x in bp]


def score(cands, second=False, subset=None, tag="j"):
    jobs = [s for s in (subset or S) if truth.get(s) and cands.get(s)]
    def one(s):
        return s, run(f"{tag}|{'2' if second else '1'}|{hash(tuple(cands[s])) & 0xffffffff}|{s}", lambda: judge(truth[s], cands[s], second))
    with cf.ThreadPoolExecutor(8) as ex: out = dict(ex.map(one, jobs))
    rec, pre, rw = {}, {}, {}
    for s, jr in out.items():
        if not jr: continue
        ac, bp = np.array(jr[0]), np.array(jr[1]); w = np.array([t["n"] for t in truth[s]], float)
        rec[s], pre[s], rw[s] = ac.mean(), bp.mean(), (ac * w).sum() / w.sum()
    return pd.DataFrame({"recall": rec, "recall_w": rw, "precision": pre})


def boot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]


resf = os.path.join(OUT, "reactions_v2.json"); res = json.load(open(resf)) if os.path.exists(resf) else {"design": __doc__.split("\n    python")[0], "variants": {}}
D0 = score(v0, tag="v0"); res["V0 site current"] = {m: boot(D0[m]) for m in D0}
print("V0", res["V0 site current"], flush=True)
for v in todo:
    usd0 = USD["usd"]
    with cf.ThreadPoolExecutor(8) as ex:
        preds = dict(zip(S, ex.map(lambda s: run(f"gen|{v}|{s}", lambda: gen(s, v)), S)))
    json.dump(C, open(cache_f, "w"))
    D = score(preds, tag=v); j = D.index.intersection(D0.index)
    lat = LAT.get(v, []); lat1 = LAT.get(v + "_p1", [])
    res["variants"][v] = {"cfg": VAR[v], **{m: boot(D[m]) for m in D}, **{f"{m} - V0 (paired)": boot(D.loc[j, m] - D0.loc[j, m]) for m in D},
                          "gen_usd_per_request": round((USD["usd"] - usd0) / max(1, len(S)), 5),
                          "median_latency_s": round(float(np.median(lat)) + (float(np.median(lat1)) if lat1 else 0), 2) if lat else None,
                          "calls_per_request": 2 if VAR[v].get("two") else 1}
    print(v, {k: res["variants"][v][k] for k in ("recall", "precision", "recall - V0 (paired)", "precision - V0 (paired)", "median_latency_s")}, flush=True)
    res["usd_total_this_run"] = round(USD["usd"], 3); json.dump(C, open(cache_f, "w")); json.dump(res, open(resf, "w"), indent=1)
if os.environ.get("CROSS"):
    v = os.environ["CROSS"]; sub = S[:100]
    best = {s: C.get(f"gen|{v}|{s}") for s in sub}
    J0 = score(v0, True, sub, "x0"); J1 = score(best, True, sub, "x" + v); j = J0.index.intersection(J1.index)
    res["cross_judge_100"] = {"variant": v, "V0": {m: boot(J0[m]) for m in J0}, v: {m: boot(J1[m]) for m in J1},
                              "diff (paired)": {m: boot(J1.loc[j, m] - J0.loc[j, m]) for m in J0}}
    print("cross", res["cross_judge_100"], flush=True)
res["usd_total_this_run"] = round(USD["usd"], 3)
json.dump(res, open(resf, "w"), indent=1); json.dump(C, open(cache_f, "w"))
