"""Validate "what users will say" (orchestrator 01:15Z Nov 12) against real Product Hunt launch comments.
Sample: launches Aug-Oct 2026 in the thread dumps (raw/ph_predict_data/comments) with >= 8 non-team comments (team = real
maker/poster handles); pilot N=30 then N=300 (SEED fixed). Product-only inputs: name, tagline, description, topics.
Steps (Gemini on Vertex, temperature 0, JSON; no Claude):
  PRED_PLAIN    the website's prompt (file passed in; placeholder until the site sends its exact prompt) -> 5 themes
  PRED_PERSONA  the same + "consider these user types" (the E5 role segments) -> 5 themes
  TRUTH         a separate call that sees only the real non-team comments (up to 40, 400 chars each) -> up to 8 themes,
                each with the number of comments raising it; never sees any prediction
  GENERIC       (baseline a) the 5 most central real themes of OTHER launches with the same first topic (embedding centrality)
  SHUFFLE       (baseline b) the PRED_PLAIN themes of a different random launch with the same first topic
  JUDGE         blinded: real theme list + one candidate list (labelled only "list B", order of candidates randomised per call)
                -> for each real theme, covered y/n; for each candidate theme, present in real comments y/n
  EMBED         gemini-embedding-001 cosine; a theme matches if cos >= 0.80 (also mean best-match cosine)
Metrics per launch: recall = share of real themes covered (weighted by comment count, and unweighted); precision = share of
candidate themes present. Means with launch-bootstrap 95% CIs; paired differences PRED - GENERIC and PRED - SHUFFLE,
PERSONA - PLAIN. The simulation counts only if PRED beats both baselines with intervals above zero.
    python reactions_eval.py <cf dir with page*.jsonl.gz> <launches dir> <prompt.txt> <out dir> <N> [model]
"""
import concurrent.futures as cf, glob, gzip, html, json, os, random, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd

CFD, LDIR, PROMPT_F, OUT, N = sys.argv[1:6]; N = int(N); MODEL = sys.argv[6] if len(sys.argv) > 6 else "gemini-2.5-flash"
os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
GEN = f"https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/{MODEL}:generateContent"
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-flash-lite": (0.10, 0.40)}.get(MODEL, (0.30, 2.50))
_tok = {"t": "", "at": 0}; USE = {"in": 0, "out": 0}


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


def gem(prompt, maxtok=1500):
    j = post(GEN, {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                   "generationConfig": {"temperature": 0, "maxOutputTokens": maxtok, "responseMimeType": "application/json",
                                        "thinkingConfig": {"thinkingBudget": 0}}})
    if not j: return None
    u = j.get("usageMetadata", {}); USE["in"] += u.get("promptTokenCount", 0); USE["out"] += u.get("candidatesTokenCount", 0)
    try: return json.loads("".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"]))
    except Exception: return None


def embed(texts):
    out = []
    for i in range(0, len(texts), 200):
        j = post(EMB, {"instances": [{"content": t, "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]], "parameters": {"outputDimensionality": 256}})
        out.append(np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32))
    E = np.vstack(out); return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


# ---------- data
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set())
             for m, p in zip(L.makers, L.poster)]
L["topic"] = L.topics.map(lambda s: (json.loads(s) or ["none"])[0] if isinstance(s, str) and s.startswith("[") else "none")
bys = {s: r for s, r in zip(L.slug, L.itertuples())}
com = {}
for f in sorted(glob.glob(os.path.join(CFD, "page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: post_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not post_ or post_.get("slug") not in bys: continue
        r = bys[post_["slug"]]
        def walk(n):
            u = ((n.get("user") or {}).get("username") or "").lower()
            t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", n.get("bodyHtml") or ""))).strip()
            if u not in r.team and len(t) > 15: com.setdefault(post_["slug"], {})[n.get("id")] = t
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((post_.get("threads") or {}).get("edges") or []): walk(e["node"])
elig = [s for s, c in com.items() if len(c) >= 8 and "2026-08" <= bys[s].day <= "2026-10-31"]
random.Random(0).shuffle(elig); S = elig[:N]
print("eligible", len(elig), "sample", len(S), flush=True)
PROMPT = open(PROMPT_F).read()
SEGS = "developers, designers, marketers, founders, product managers, data/AI practitioners, sales people, students, investors"


def inputs(s):
    r = bys[s]; return {"name": r.name, "tagline": r.tagline or "", "description": (r.description or "")[:1500],
                        "topics": ", ".join(json.loads(r.topics)) if isinstance(r.topics, str) and r.topics.startswith("[") else ""}


def pred(s, persona):
    p = PROMPT.format(**inputs(s))
    if persona: p += f"\n\nConsider how each of these user types would react before choosing the themes: {SEGS}."
    a = gem(p); th = (a or {}).get("themes") if isinstance(a, dict) else a
    return [str(t.get("theme", t)) if isinstance(t, dict) else str(t) for t in (th or [])][:5]


TRUTH = """Below are real user comments on a product launch (makers' own comments removed). Extract the main themes users
raised: praise, objections/concerns, questions, feature requests, comparisons to named alternatives. Return JSON
{{"themes": [{{"type": "...", "theme": "<one specific sentence>", "n_comments": <int>}}]}} with at most 8 themes, most frequent first.
Generic thanks/congratulations with no content count as one theme at most.
Comments:
{c}"""


def truth(s):
    c = "\n".join(f"- {t[:400]}" for t in list(com[s].values())[:40])
    a = gem(TRUTH.format(c=c), 2000); th = (a or {}).get("themes", []) if isinstance(a, dict) else []
    return [{"theme": str(t.get("theme", "")), "n": max(1, int(t.get("n_comments", 1) or 1))} for t in th if isinstance(t, dict) and t.get("theme")][:8]


JUDGE = """List A = themes real users raised about a product. List B = candidate themes.
For each item in A, say whether some item in B substantially covers the same point (same concern/praise/question/request,
not merely the same broad area). For each item in B, say whether it substantially matches some item in A.
Return JSON {{"a_covered": [true/false per A item], "b_present": [true/false per B item]}}.
A:
{a}
B:
{b}"""


def judge(real, cand):
    a = gem(JUDGE.format(a="\n".join(f"{i+1}. {t['theme']}" for i, t in enumerate(real)), b="\n".join(f"{i+1}. {t}" for i, t in enumerate(cand))), 500)
    if not isinstance(a, dict): return None
    ac, bp = a.get("a_covered", []), a.get("b_present", [])
    if len(ac) != len(real) or len(bp) != len(cand): return None
    return [bool(x) for x in ac], [bool(x) for x in bp]


cache_f = os.path.join(OUT, "cache.json"); C = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(fn, key, *a):
    if key not in C: C[key] = fn(*a)
    return C[key]
with cf.ThreadPoolExecutor(8) as ex:
    list(ex.map(lambda s: (run(pred, f"plain|{s}", s, False), run(pred, f"persona|{s}", s, True), run(truth, f"truth|{s}", s)), S))
json.dump(C, open(cache_f, "w"))
print("generated; usd so far", round(USE["in"] / 1e6 * PRICE[0] + USE["out"] / 1e6 * PRICE[1], 3), flush=True)

# baselines
topic = {s: bys[s].topic for s in S}
alltruth = {s: C[f"truth|{s}"] for s in S if C.get(f"truth|{s}")}
texts = sorted({t["theme"] for v in alltruth.values() for t in v} | {t for s in S for k in ("plain", "persona") for t in (C.get(f"{k}|{s}") or [])})
EV = embed(texts); eix = {t: i for i, t in enumerate(texts)}
generic, shuffle = {}, {}
for s in S:
    pool = [t["theme"] for o, v in alltruth.items() if o != s and topic[o] == topic[s] for t in v]
    if len(pool) < 5: pool = [t["theme"] for o, v in alltruth.items() if o != s for t in v]
    M = EV[[eix[t] for t in pool]]; cen = (M @ M.T).mean(1); generic[s] = [pool[i] for i in np.argsort(-cen)[:5]]
    others = [o for o in S if o != s and topic[o] == topic[s] and C.get(f"plain|{o}")] or [o for o in S if o != s and C.get(f"plain|{o}")]
    shuffle[s] = C[f"plain|{random.Random(hash(s) % 1000).choice(others)}"]
cands = {"PRED_PLAIN": {s: C.get(f"plain|{s}") for s in S}, "PRED_PERSONA": {s: C.get(f"persona|{s}") for s in S}, "GENERIC_TOPIC": generic, "SHUFFLE_SAME_TOPIC": shuffle}
jobs = [(nm, s) for nm in cands for s in S if alltruth.get(s) and cands[nm].get(s)]
random.Random(1).shuffle(jobs)                                          # judge calls interleaved across candidate types
with cf.ThreadPoolExecutor(8) as ex:
    JR = dict(zip(jobs, ex.map(lambda j: run(lambda: judge(alltruth[j[1]], cands[j[0]][j[1]]), f"judge|{j[0]}|{j[1]}"), jobs)))
json.dump(C, open(cache_f, "w"))
rows = []
for (nm, s), jr in JR.items():
    real = alltruth[s]; cand = cands[nm][s]; w = np.array([t["n"] for t in real], float)
    R = EV[[eix[t["theme"]] for t in real]]; Q = EV[[eix[t] for t in cand]]; Sm = R @ Q.T
    r = {"cand": nm, "slug_idx": S.index(s), "emb_recall": float((Sm.max(1) >= 0.80).mean()), "emb_precision": float((Sm.max(0) >= 0.80).mean()),
         "emb_best_cos": float(Sm.max(1).mean())}
    if jr:
        ac, bp = np.array(jr[0]), np.array(jr[1])
        r.update({"judge_recall": float(ac.mean()), "judge_recall_w": float((ac * w).sum() / w.sum()), "judge_precision": float(bp.mean())})
    rows.append(r)
D = pd.DataFrame(rows)


def boot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(v))]


MET = ["judge_recall", "judge_recall_w", "judge_precision", "emb_recall", "emb_precision", "emb_best_cos"]
P_ = D.pivot_table(index="slug_idx", columns="cand", values=MET)
res = {"design": __doc__.split("\n    python")[0], "model": MODEL, "eligible": len(elig), "n": len(S),
       "usd": round(USE["in"] / 1e6 * PRICE[0] + USE["out"] / 1e6 * PRICE[1], 3), "means": {}, "paired": {}}
for nm in cands: res["means"][nm] = {m: boot(P_[(m, nm)]) for m in MET if (m, nm) in P_}
for a, b in (("PRED_PLAIN", "GENERIC_TOPIC"), ("PRED_PLAIN", "SHUFFLE_SAME_TOPIC"), ("PRED_PERSONA", "GENERIC_TOPIC"), ("PRED_PERSONA", "SHUFFLE_SAME_TOPIC"), ("PRED_PERSONA", "PRED_PLAIN")):
    res["paired"][f"{a} - {b}"] = {m: boot(P_[(m, a)] - P_[(m, b)]) for m in MET if (m, a) in P_ and (m, b) in P_}
ex_s = S[0]
res["example (first sample launch, product name withheld)"] = {"truth": [t["theme"] for t in alltruth.get(ex_s, [])], "pred_plain": cands["PRED_PLAIN"][ex_s], "generic": generic[ex_s]}
json.dump(res, open(os.path.join(OUT, f"reactions_eval_n{N}.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1))
