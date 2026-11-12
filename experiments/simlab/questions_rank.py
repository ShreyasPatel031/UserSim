"""QUESTIONS variant (orchestrator 03:00Z Nov 12, item 2): what makers get asked in the first hours. Same machinery as the ranked
"top concerns" list below, with truth = only the QUESTIONS real users asked (separate flash extraction), the critic replaced by a
question generator, retrieval restricted to "question:" themes, and a generic question list as the base rate.
Original design notes follow.
A ranked "top concerns" list for new products (orchestrator 02:50Z Nov 12). Same 300 post-cutoff launches (Aug-Oct 2026) and
critical-theme truth as complaints_eval.py Part B (objections, doubting questions, feature requests from the real comments).
Candidate generators (all product-only or earlier data):
  DEPLOYED   the site's BEST reactions (reactions_v2 cache), in their order
  CRITIC     the D_category critic list (complaints_eval cache), in its order
  RETRIEVED  critical themes ("objection / question / feature request" items) of the k = 25 most similar EARLIER launches
             (reactions_retrieval_v1 bundle; same slug stem / name excluded), ordered by how many neighbours raised a similar
             theme (gemini-embedding cosine >= 0.80)
  BASE       category base-rate list: the 5 most frequent critical themes among earlier launches with the same first topic
             (frequency = number of launches with a theme within cosine 0.80; medoid text), no product information
  RANKED     all candidates above pooled and scored by the mean of three rank-normalised signals, weights fixed in advance:
             (a) neighbour frequency among the 25 similar earlier launches, (b) agreement = number of candidates from OTHER
             generators within cosine 0.80, (c) a Gemini 2.5 Flash self-rated likelihood (1-5) given only product text;
             near-duplicates (cos >= 0.90) collapsed; top 5 kept
Judge (blinded, gemini-2.5-flash): for each listed concern, does it substantially match a real critical theme; precision@1/3/5,
hit@3; launch-bootstrap 95% CIs; paired vs BASE and vs DEPLOYED; split by first topic.
    python concerns_rank.py <complaints out dir (cache.json)> <react_v2 dir (cache_v2.json)> <rbundle dir> <cf dir> <launches dir> <out dir>
"""
import concurrent.futures as cf, glob, gzip, html, json, os, random, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd

CO, RV2, RB, CFD, LDIR, OUT = sys.argv[1:7]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
GEN = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/gemini-2.5-flash:generateContent"
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
_tok = {"t": "", "at": 0}; USD = {"usd": 0.0}


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


def gem(prompt, maxtok=1200):
    j = post(GEN, {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0, "maxOutputTokens": maxtok, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}})
    if not j: return None
    u = j.get("usageMetadata", {}); USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * 0.30 + u.get("candidatesTokenCount", 0) / 1e6 * 2.50
    try: return json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"]))
    except Exception: return None


def embed(texts):
    out = []
    for i in range(0, len(texts), 200):
        j = post(EMB, {"instances": [{"content": t[:1000], "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]], "parameters": {"outputDimensionality": 256}})
        out.append(np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32))
    E = np.vstack(out) if out else np.zeros((0, 256), np.float32); return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


# same 300 launches as complaints_eval Part B
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
CC = json.load(open(os.path.join(CO, "cache.json"))); RVC = json.load(open(os.path.join(RV2, "cache_v2.json")))
QT = """Below are real user comments on a product launch (makers' own comments removed). Extract ONLY the QUESTIONS users asked
the makers (explicit questions or clear requests for information). Ignore praise and statements.
Return JSON {{"questions": ["<one specific question>", ...]}} with at most 6, most frequent first (empty list if none).
Comments:
{c}"""
cache_f0 = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f0)) if os.path.exists(cache_f0) else {}
def run(key, fn):
    if key not in K: K[key] = fn()
    return K[key]
with cf.ThreadPoolExecutor(8) as ex:
    TRUTH = dict(zip(S, ex.map(lambda s: run(f"qtruth|{s}", lambda: (gem(QT.format(c="\n".join(f"- {t[:400]}" for t in list(com[s].values())[:40]))) or {}).get("questions") or []), S)))
json.dump(K, open(cache_f0, "w"))
DEPLOYED = {s: RVC.get(f"gen|BEST|{s}") or [] for s in S}
QG = """A new product is launching on Product Hunt today.
Product: {name} - {tagline}
Description: {desc}
List the 6 questions users are most likely to ask the makers in the launch comments in the first hours, most likely first.
Be specific to this product; do not invent features. Return JSON {{"questions": ["...", ...]}}"""
with cf.ThreadPoolExecutor(8) as ex:
    CRITIC = dict(zip(S, ex.map(lambda s: run(f"qgen|{s}", lambda: (gem(QG.format(name=bys[s].name, tagline=bys[s].tagline, desc=(bys[s].description or "")[:1200])) or {}).get("questions") or []), S)))
json.dump(K, open(cache_f0, "w"))
RBE = np.load(os.path.join(RB, "reactions_retrieval_v1.npz"))["emb"].astype(np.float32); RBM = json.load(open(os.path.join(RB, "reactions_retrieval_v1.json")))
CRIT = re.compile(r"^\s*(question)\s*:\s*", re.I)
crit_themes = [[CRIT.sub("", t) for t in m["themes"] if CRIT.match(t)] for m in RBM]
all_ct = sorted({t for v in crit_themes for t in v}); cf_ = os.path.join(OUT, "ct_emb.npy")
CE = np.load(cf_) if os.path.exists(cf_) and np.load(cf_).shape[0] == len(all_ct) else embed(all_ct); np.save(cf_, CE); cix = {t: i for i, t in enumerate(all_ct)}
QE = embed([f"{bys[s].name}. {bys[s].tagline}. {(bys[s].description or '')[:800]}" for s in S])
stem = lambda s: re.sub(r"-\d+$", "", s)
rb_topic = [m["topic"] for m in RBM]; rb_day = [m["day"] for m in RBM]
print("launches", len(S), "with truth", sum(bool(v) for v in TRUTH.values()), "critical themes in bundle", len(all_ct), flush=True)


def freq_list(rows, k_out, min_cos=0.80):
    """themes from a set of launch rows -> (text, number of launches raising a similar theme), medoid order"""
    items = [(t, r) for r in rows for t in crit_themes[r]]
    if not items: return []
    X = CE[[cix[t] for t, _ in items]]; S_ = X @ X.T; own = np.array([r for _, r in items])
    cnt = np.array([len(set(own[S_[i] >= min_cos])) for i in range(len(items))])
    out, used = [], np.zeros(len(items), bool)
    for i in np.argsort(-cnt):
        if used[i]: continue
        out.append((items[i][0], int(cnt[i]))); used |= S_[i] >= min_cos
        if len(out) == k_out: break
    return out


RETR, BASE, NB = {}, {}, {}
for qi, s in enumerate(S):
    r = bys[s]; sims = RBE @ QE[qi]; nb = []
    for j in np.argsort(-sims):
        if rb_day[j] >= r.day or RBM[j]["slug_stem"] == stem(s) or s.startswith(RBM[j]["slug_stem"]): continue
        nb.append(j)
        if len(nb) == 25: break
    NB[s] = nb; RETR[s] = [t for t, _ in freq_list(nb, 8)]
    earlier_topic = [j for j in range(len(RBM)) if rb_day[j] < r.day and rb_topic[j] == r.topic]
    if len(earlier_topic) < 20: earlier_topic = [j for j in range(len(RBM)) if rb_day[j] < r.day]
    BASE[s] = [t for t, _ in freq_list(list(rng.choice(earlier_topic, min(300, len(earlier_topic)), replace=False)), 5)]
print("retrieval/base built", flush=True)
cache_f = cache_f0
LIKE = """A new product is launching on Product Hunt.
Product: {name} - {tagline}
Description: {desc}
Below are candidate questions users might ask the makers in the launch comments.
Rate how likely real users are to ask each one for THIS product, 1 (unlikely) to 5 (very likely).
Return JSON {{"ratings": [1-5 per candidate, in order]}}
{c}"""


def ranked(qi, s):
    cands = [(t, "DEPLOYED") for t in DEPLOYED[s]] + [(t, "CRITIC") for t in CRITIC[s]] + [(t, "RETRIEVED") for t in RETR[s]] + [(t, "BASE") for t in BASE[s]]
    cands = [(t, g) for t, g in cands if t]
    if not cands: return []
    X = embed([t for t, _ in cands]); S_ = X @ X.T; gens = np.array([g for _, g in cands])
    nbt = [t for j in NB[s] for t in crit_themes[j]]; NBX = CE[[cix[t] for t in nbt]] if nbt else np.zeros((0, 256), np.float32)
    nbown = np.array([j for j in NB[s] for _ in crit_themes[j]])
    a = np.array([len(set(nbown[(NBX @ X[i]) >= 0.80])) if len(nbt) else 0 for i in range(len(cands))], float)
    b = np.array([((S_[i] >= 0.80) & (gens != gens[i])).sum() for i in range(len(cands))], float)
    r = bys[s]; lk = run(f"qlike|{s}", lambda: (gem(LIKE.format(name=r.name, tagline=r.tagline, desc=(r.description or "")[:1200], c="\n".join(f"{k+1}. {t[:300]}" for k, (t, _) in enumerate(cands)))) or {}).get("ratings"))
    c = np.array(lk if isinstance(lk, list) and len(lk) == len(cands) else [3] * len(cands), float)
    rk = lambda v: pd.Series(v).rank(pct=True).to_numpy()
    sc = (rk(a) + rk(b) + rk(c)) / 3
    out, used = [], np.zeros(len(cands), bool)
    for i in np.argsort(-sc):
        if used[i]: continue
        out.append(cands[i][0]); used |= S_[i] >= 0.90
        if len(out) == 5: break
    return out


with cf.ThreadPoolExecutor(6) as ex: RANKED = dict(zip(S, ex.map(lambda qs: run(f"qranked|{qs[1]}", lambda: ranked(*qs)), list(enumerate(S)))))
json.dump(K, open(cache_f, "w")); print("ranked usd", round(USD["usd"], 3), flush=True)
JQ = """List A = questions real users asked the makers of a product launch. List B = a ranked list of predicted questions or
reactions. For each item in B, does it substantially match some question in A (asks for the same specific thing, not merely the
same broad area)? Return JSON {{"b_matches": [true/false per B item]}}
A:
{a}
B:
{b}"""
METHODS = {"DEPLOYED": DEPLOYED, "CRITIC": CRITIC, "RETRIEVED": RETR, "BASE": BASE, "RANKED": RANKED}
def judge(s, m):
    lst = METHODS[m][s][:5]
    if not TRUTH[s] or not lst: return None
    a = gem(JQ.format(a="\n".join(f"{k+1}. {t}" for k, t in enumerate(TRUTH[s])), b="\n".join(f"{k+1}. {t[:300]}" for k, t in enumerate(lst))), 300)
    bm = (a or {}).get("b_matches")
    return [bool(x) for x in bm] if isinstance(bm, list) and len(bm) == len(lst) else None
jobs = [(s, m) for s in S for m in METHODS]; random.Random(2).shuffle(jobs)
with cf.ThreadPoolExecutor(8) as ex: J = dict(zip(jobs, ex.map(lambda j: run(f"qj|{j[1]}|{j[0]}", lambda: judge(*j)), jobs)))
json.dump(K, open(cache_f, "w"))
rows = []
for (s, m), bm in J.items():
    if bm is None: continue
    bm = np.array(bm, float)
    rows.append({"s": s, "m": m, "topic": bys[s].topic, "p1": bm[:1].mean(), "p3": bm[:3].mean(), "p5": bm[:5].mean(), "hit3": float(bm[:3].any())})
D = pd.DataFrame(rows)


def boot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]


MET = ["p1", "p3", "p5", "hit3"]; W = D.pivot_table(index="s", columns="m", values=MET)
res = {"design": __doc__.split("\n    python")[0], "launches": len(S), "means": {m: {k: boot(D[D.m == m][k]) for k in MET} for m in METHODS}, "paired": {}}
for a in ("RANKED", "DEPLOYED", "CRITIC", "RETRIEVED"):
    for b in ("BASE", "DEPLOYED"):
        if a != b: res["paired"][f"{a} - {b}"] = {k: boot(W[(k, a)] - W[(k, b)]) for k in MET}
top_topics = D[D.m == "RANKED"].topic.value_counts().index[:6]
res["by_topic (p3)"] = {t: {m: boot(D[(D.m == m) & (D.topic == t)].p3) for m in ("RANKED", "BASE", "DEPLOYED")} for t in top_topics}
res["truth_questions_nonempty"] = int(sum(bool(v) for v in TRUTH.values())); res["examples_base_list"] = {bys[s].topic: BASE[s] for s in S[:6]}
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "questions_rank.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str)[:4000])

# ---------- fairer base-rate bar: fixed generic concerns, ordered per topic by frequency among earlier launches
GENERIC = ["How much does it cost - is there a free tier?", "How is my data handled and is it private?",
           "Does it integrate with the tools I already use?", "Is there a mobile app or is mobile support planned?", "Is it open source or can I self-host it?",
           "How is it different from the established alternative?", "What is on the roadmap next?"]
GE = embed(GENERIC); BASE2 = {}
for qi, s in enumerate(S):
    r = bys[s]; et = [j for j in range(len(RBM)) if rb_day[j] < r.day and rb_topic[j] == r.topic]
    if len(et) < 20: et = [j for j in range(len(RBM)) if rb_day[j] < r.day]
    ths = [t for j in et for t in crit_themes[j]]
    if ths:
        X = CE[[cix[t] for t in ths]]; f = (X @ GE.T >= 0.70).sum(0)
    else:
        f = np.zeros(len(GENERIC))
    BASE2[s] = [GENERIC[i] for i in np.argsort(-f)][:5]
METHODS["BASE_GENERIC"] = BASE2
jobs2 = [(s, "BASE_GENERIC") for s in S]
with cf.ThreadPoolExecutor(8) as ex: J2 = dict(zip(jobs2, ex.map(lambda j: run(f"qj|{j[1]}|{j[0]}", lambda: judge(*j)), jobs2)))
json.dump(K, open(cache_f, "w"))
for (s, m), bm in J2.items():
    if bm is None: continue
    bm = np.array(bm, float)
    rows.append({"s": s, "m": m, "topic": bys[s].topic, "p1": bm[:1].mean(), "p3": bm[:3].mean(), "p5": bm[:5].mean(), "hit3": float(bm[:3].any())})
D = pd.DataFrame(rows); W = D.pivot_table(index="s", columns="m", values=MET)
res["means"]["BASE_GENERIC"] = {k: boot(D[D.m == "BASE_GENERIC"][k]) for k in MET}
for a in ("RANKED", "DEPLOYED", "CRITIC"):
    res["paired"][f"{a} - BASE_GENERIC"] = {k: boot(W[(k, a)] - W[(k, "BASE_GENERIC")]) for k in MET}
res["by_topic (p3) generic"] = {t: boot(D[(D.m == "BASE_GENERIC") & (D.topic == t)].p3) for t in top_topics}
res["generic_order_examples"] = {bys[s].topic: BASE2[s][:3] for s in S[:6]}
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "questions_rank.json"), "w"), indent=1, default=str)
print("GENERIC", json.dumps({k: res[k] for k in ("usd",)}), json.dumps(res["means"]["BASE_GENERIC"]), json.dumps({k: v for k, v in res["paired"].items() if "GENERIC" in k}))
