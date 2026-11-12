"""Self-consistency for concerns and model strength (orchestrator 04:00Z Nov 12, item 2). Same 300 post-cutoff launches and
critical-theme truth as concerns_rank (complaints_eval ctruth).
  SC5      the D_category critic prompt (launch framing, as in complaints_eval Part B) sampled 5 times at temperature 0.9
           (gemini-2.5-flash); items embedded (gemini-embedding-001, 256-d) and clustered greedily at cosine >= 0.85; clusters
           ranked by how many of the 5 samples raise them (ties: earlier mean position); medoid text; top 5
  MERGED   RANKED top 5 (concerns_rank) + SC5 top 5 pooled, near-duplicates (cos >= 0.85) merged, ranked by the mean of
           (RANKED position score) and (SC support / 5) - support as a fourth vote
  PRO      the same D critic prompt, single call, gemini-2.5-pro (temperature 0.3, minimal thinking) vs the flash single call
           (CRITIC in concerns_rank)
Same blinded judge as concerns_rank (per-item b_matches); p@1, p@3, hit@3; launch-bootstrap CIs; paired vs RANKED and vs
CRITIC; cost and latency per request.
    python consistency.py <compl dir (cache.json: ctruth, critB)> <conc dir (cache.json: ranked, j|...)> <launches dir> <cf dir> <out dir>
"""
import concurrent.futures as cf, glob, gzip, hashlib, html, json, os, random, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd

CO, CON, LDIR, CFD, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
BASE = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/{m}:generateContent"
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-pro": (1.25, 10.0)}
_tok = {"t": "", "at": 0}; USD = {"usd": 0.0}; LAT = {}


def token():
    if time.time() - _tok["at"] > 300:
        _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
    return _tok["t"]


def post(url, body):
    for i in range(6):
        try:
            req = urllib.request.Request(url, json.dumps(body).encode(), {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=240))
        except Exception as e:  # noqa: BLE001
            print("retry", i, str(e)[:100], flush=True); time.sleep(4 * (i + 1))
    return None


def gem(prompt, model="gemini-2.5-flash", temp=0.0, maxtok=1500, tag=None):
    think = {"thinkingBudget": 128} if "pro" in model else {"thinkingBudget": 0}
    t0 = time.time()
    j = post(BASE.format(m=model), {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                                    "generationConfig": {"temperature": temp, "maxOutputTokens": maxtok, "responseMimeType": "application/json", "thinkingConfig": think}})
    if tag: LAT.setdefault(tag, []).append(time.time() - t0)
    if not j: return None
    u = j.get("usageMetadata", {}); p = PRICE[model]
    USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * p[0] + (u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)) / 1e6 * p[1]
    try: return json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"] if "text" in x))
    except Exception: return None


def embed(texts):
    out = []
    for i in range(0, len(texts), 200):
        j = post(EMB, {"instances": [{"content": t[:1000], "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]], "parameters": {"outputDimensionality": 256}})
        out.append(np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32))
    E = np.vstack(out); return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set()) for m, p in zip(L.makers, L.poster)]
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
CC = json.load(open(os.path.join(CO, "cache.json"))); CN = json.load(open(os.path.join(CON, "cache.json")))
TRUTH = {s: CC.get(f"ctruth|{s}") or [] for s in S}; RANKED = {s: CN.get(f"ranked|{s}") or [] for s in S}; CRITIC1 = {s: CC.get(f"critB|D_category|{s}") or [] for s in S}
DPROMPT = ("List the {k} criticisms most likely from real users: first the complaints users of this product CATEGORY almost always raise (2-3), "
           "then the ones SPECIFIC to this product (the rest). Do not invent features.\nProduct: {name}\nDescription: {desc}\n\n"
           "Return JSON {{\"criticisms\": [\"<one specific sentence>\", ...]}}")
card = lambda s: f"{bys[s].name}. {bys[s].tagline}. {(bys[s].description or '')[:1300]}"
cache_f = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(key, fn):
    if key not in K: K[key] = fn()
    return K[key]
def sample(s, k, model="gemini-2.5-flash", temp=0.9, tag="sc"):
    return [str(x) for x in ((gem(DPROMPT.format(k=6, name=bys[s].name, desc=card(s)), model, temp, 1500 if "flash" in model else 4000, tag=tag) or {}).get("criticisms") or [])][:6]
jobs = [(s, k) for s in S for k in range(5)]
with cf.ThreadPoolExecutor(10) as ex: SAMP = dict(zip(jobs, ex.map(lambda j: run(f"sc|{j[0]}|{j[1]}", lambda: sample(*j)), jobs)))
with cf.ThreadPoolExecutor(6) as ex: PRO = dict(zip(S, ex.map(lambda s: run(f"pro|{s}", lambda: sample(s, 0, "gemini-2.5-pro", 0.3, "pro")), S)))
json.dump(K, open(cache_f, "w")); print("generated usd", round(USD["usd"], 3), flush=True)
SC5, MERGED = {}, {}
for s in S:
    items = [(t, k, i) for k in range(5) for i, t in enumerate(SAMP[(s, k)] or [])]
    if not items: SC5[s] = []; MERGED[s] = RANKED[s]; continue
    X = embed([t for t, _, _ in items]); Sm = X @ X.T; used = np.zeros(len(items), bool); cl = []
    for i in range(len(items)):
        if used[i]: continue
        mem = np.flatnonzero((Sm[i] >= 0.85) & ~used); used[mem] = True
        sup = len({items[m][1] for m in mem}); pos = np.mean([items[m][2] for m in mem])
        med = mem[np.argmax(Sm[np.ix_(mem, mem)].sum(1))]; cl.append((sup, -pos, items[med][0], X[med]))
    cl.sort(key=lambda c: (-c[0], -c[1])); SC5[s] = [c[2] for c in cl[:5]]
    rk = RANKED[s]
    if rk:
        RX = embed(rk); cand = [(t, (5 - i) / 5, max([c[0] for c in cl if float(c[3] @ RX[i]) >= 0.85] or [0]) / 5, RX[i]) for i, t in enumerate(rk)]
        for c in cl[:5]:
            if not any(float(c[3] @ x[3]) >= 0.85 for x in cand): cand.append((c[2], 0.0, c[0] / 5, c[3]))
        cand.sort(key=lambda c: -(c[1] + c[2]) / 2); MERGED[s] = [c[0] for c in cand[:5]]
    else: MERGED[s] = SC5[s]
JC = """List A = critical points real users raised about a product launch (objections, doubting questions, feature requests).
List B = a ranked list of predicted concerns. For each item in B, does it substantially match some item in A (the same specific
concern, not merely the same broad area)? Return JSON {{"b_matches": [true/false per B item]}}
A:
{a}
B:
{b}"""
num = lambda l: "\n".join(f"{k+1}. {t[:300]}" for k, t in enumerate(l))
def judge(s, nm, lst):
    if not TRUTH[s] or not lst: return None
    bm = (gem(JC.format(a=num(TRUTH[s]), b=num(lst[:5])), maxtok=300) or {}).get("b_matches")
    return [bool(x) for x in bm] if isinstance(bm, list) and len(bm) == len(lst[:5]) else None
METH = {"SC5": SC5, "MERGED": MERGED, "PRO": PRO}
jobs = [(s, m) for s in S for m in METH]
with cf.ThreadPoolExecutor(10) as ex: J = dict(zip(jobs, ex.map(lambda j: run(f"j|{j[1]}|{hashlib.md5(json.dumps(METH[j[1]][j[0]]).encode()).hexdigest()[:8]}|{j[0]}", lambda: judge(j[0], j[1], METH[j[1]][j[0]])), jobs)))
json.dump(K, open(cache_f, "w"))
rows = []
for s in S:
    for nm in ("RANKED", "CRITIC"):
        v = CN.get(f"j|{nm}|{s}")
        if v: rows.append({"s": s, "m": nm, "p1": float(v[0]), "p3": float(np.mean(v[:3])), "hit3": float(any(v[:3]))})
    for nm in METH:
        v = J.get((s, nm))
        if v: rows.append({"s": s, "m": nm, "p1": float(v[0]), "p3": float(np.mean(v[:3])), "hit3": float(any(v[:3]))})
D = pd.DataFrame(rows); W = D.pivot_table(index="s", columns="m", values=["p1", "p3", "hit3"])


def mb(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]


res = {"design": __doc__.split("\n    python")[0], "means": {m: {k: mb(D[D.m == m][k]) for k in ("p1", "p3", "hit3")} for m in ("RANKED", "CRITIC", "SC5", "MERGED", "PRO")}, "paired": {}}
for a, b in (("SC5", "RANKED"), ("MERGED", "RANKED"), ("PRO", "CRITIC"), ("PRO", "RANKED"), ("SC5", "CRITIC")):
    res["paired"][f"{a} - {b}"] = {k: mb(W[(k, a)] - W[(k, b)]) for k in ("p1", "p3", "hit3")}
res["latency_median_s"] = {k: round(float(np.median(v)), 2) for k, v in LAT.items()}
res["cost_note"] = "SC5 = 5 flash calls + 1 embedding batch per request; PRO = 1 pro call"
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "consistency.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
