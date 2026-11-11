"""Does "what users will say" hold outside launch threads? (orchestrator 23:30Z Nov 11). Truth = real post-use product reviews
(Product Hunt product reviews, raw/ph_predict_data/competitor_reviews.jsonl.gz: personal and founder reviews, text + pros/cons;
reviewer names never read). Products with >= 10 reviews (229; 228 with product text). Product-only inputs: name, tagline,
description (uses export products.parquet card text).
Generators (gemini-2.5-flash, temperature 0.3, 6 comments, E5 member types + 2 contrast types, as the site's BEST):
  U0_launch   the site's REACT_PROMPT as deployed (launch-day framing) + PH launch-theme retrieval (k = 10)
  U1_postuse  post-use framing ("reviews written after using it: praise, complaints, missing features, comparisons"), no retrieval
  U2_postuse_R  U1 + PH launch-theme retrieval (k = 10, same bundle; excluded same slug stem / name)
Truth: separate gemini-2.5-flash pass over up to 40 reviews (text + pros/cons, 500 chars each) -> up to 8 themes, each typed
praise / complaint / missing_feature / comparison, with counts. Controls: category = k-means cluster (12) of the products'
gemini embeddings; GENERIC = the 6 most central truth themes of other products in the cluster; SHUFFLE = U1 prediction of
another product in the cluster. Same blinded judge as reactions_eval. Recall overall and by truth-theme type (praise vs
complaint + missing feature); precision; product-bootstrap 95% CIs; paired differences.
    python reviews_eval.py <competitor_reviews.jsonl.gz> <uses2 export dir> <try_sim.py> <retrieval bundle dir> <person bundle> <out dir>
"""
import ast, concurrent.futures as cf, gzip, hashlib, json, os, random, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd
from sklearn.cluster import KMeans

REV, EXP, TRY, RB, PB, OUT = sys.argv[1:7]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
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


def gem(prompt, temp=0.0, maxtok=3000):
    j = post(GEN, {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                   "generationConfig": {"temperature": temp, "maxOutputTokens": maxtok, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}})
    if not j: return None
    u = j.get("usageMetadata", {}); USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * 0.30 + u.get("candidatesTokenCount", 0) / 1e6 * 2.50
    try: return json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"]))
    except Exception: return None


def embed(texts):
    out = []
    for i in range(0, len(texts), 200):
        j = post(EMB, {"instances": [{"content": t[:2000], "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]], "parameters": {"outputDimensionality": 256}})
        out.append(np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32))
    E = np.vstack(out); return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


P = pd.read_parquet(os.path.join(EXP, "products.parquet")); card = dict(zip(P.slug, P.rich_text.fillna(P.text)))
prods = []
for line in gzip.open(REV):
    r = json.loads(line)
    if str(r["status"]) != "200": continue
    rv = r["reviews"] if isinstance(r["reviews"], list) else json.loads(r["reviews"])
    if len(rv) >= 10 and r["slug"] in card:
        txt = [" ".join(x for x in (v.get("text"), ("Pros: " + v["pros"]) if v.get("pros") else None, ("Cons: " + v["cons"]) if v.get("cons") else None) if x)[:500] for v in rv]
        prods.append({"slug": r["slug"], "name": r["competitor"], "card": card[r["slug"]], "reviews": [t for t in txt if len(t) > 20]})
print("products", len(prods), flush=True)
cache_f = os.path.join(OUT, "cache.json"); C = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(key, fn):
    if key not in C: C[key] = fn()
    return C[key]

E = embed([p["card"][:1500] for p in prods])
km = KMeans(12, n_init=10, random_state=0).fit(E); cl = km.labels_
RBE = np.load(os.path.join(RB, "reactions_retrieval_v1.npz"))["emb"].astype(np.float32); RBM = json.load(open(os.path.join(RB, "reactions_retrieval_v1.json")))
stem = lambda s: re.sub(r"-\d+$", "", s)

# member types from the E5 scorer (same as reactions_v2)
BZ = np.load(PB); IE = BZ["item_emb"].astype(np.float32); PTR, IDX = BZ["person_ptr"], BZ["person_items"]
TR = {k: BZ[k] for k in ("tree_feat", "tree_thr", "tree_left", "tree_right", "tree_value", "tree_roots")}; RN = list(BZ["role_names"]); NU = BZ["n_uses"]
def member_types(q):
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
    for j in np.argsort(-(sc - BZ["pct99_tree"])):
        ro = tuple(RN[k] for k in np.flatnonzero(BZ["roles"][j])) or ("member",); ti = "1-3 tools" if NU[j] <= 3 else ("4-10 tools" if NU[j] <= 10 else "11+ tools")
        if (ro, ti) in seen: continue
        seen.add((ro, ti)); out.append(f"{' / '.join(ro)}, {ti}")
        if len(out) == 4: break
    return out
CONTRAST = ["heavy PH voter who comments often and sees dozens of similar launches a week", "maker from an unrelated category, browsing the day's launches"]
SITE_PROMPT = next(n.value.value for n in ast.parse(open(TRY).read()).body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "REACT_PROMPT")
POST = """Simulate what real users of this product say in reviews written AFTER using it for a while: praise, complaints, missing
features, and comparisons to named alternatives. Write one review-style comment per user type below.
Product: {name}
Description: {desc}

Each is a TYPE of user (not a real individual). Stay grounded in the description: do not invent features. Mix satisfaction and
frustration realistically. Never use real names or @handles.
User types:
{types}

Return JSON: {{"reactions": [{{"type": "<copy the type label>", "comment": "1-3 sentences", "sentiment": "positive|mixed|negative", "why": "one short reason"}}]}}"""
GROUND = "\n\nFor grounding: users of similar past Product Hunt products raised these points (other products, not this one; reuse only what plausibly applies here):\n"


def gen(i, variant):
    p = prods[i]; q = E[i]
    types = [f"User {chr(65 + k)}: {t}" for k, t in enumerate(run(f"mt|{p['slug']}", lambda: member_types(q)) + CONTRAST)]
    desc = p["card"][:1500]; name = p["name"]
    if variant == "U0_launch":
        pr = SITE_PROMPT.format(name=name, tagline="", summary=desc, pricing="unknown", strengths="", doubts="", excerpt=desc[:2500], types="\n".join(types))
    else:
        pr = POST.format(name=name, desc=desc, types="\n".join(types))
    if variant in ("U0_launch", "U2_postuse_R"):
        s = RBE @ q; th = []
        for j in np.argsort(-s):
            m = RBM[j]
            if m["slug_stem"] == stem(p["slug"]) or p["slug"].startswith(m["slug_stem"]): continue
            th += m["themes"]
            if len(th) >= 60 or j is None: break
            if sum(1 for _ in th) and len(th) >= 60: break
        pr += GROUND + "\n".join(f"- {t}" for t in th[:60])
    a = gem(pr, 0.3)
    return [f"{x.get('comment', '')} ({x.get('why', '')})" for x in ((a or {}).get("reactions") or []) if isinstance(x, dict)][:6]


TRUTH = """Below are real user reviews of a product (written after using it). Extract the main themes reviewers raised.
Return JSON {{"themes": [{{"type": "praise|complaint|missing_feature|comparison", "theme": "<one specific sentence>", "n_reviews": <int>}}]}}
with at most 8 themes, most frequent first. Generic satisfaction with no content counts as one theme at most.
Reviews:
{c}"""
def truth(i):
    a = gem(TRUTH.format(c="\n".join(f"- {t}" for t in prods[i]["reviews"][:40])), 0.0, 2000)
    th = (a or {}).get("themes", []) if isinstance(a, dict) else []
    return [{"theme": str(t.get("theme")), "type": str(t.get("type", "")), "n": max(1, int(t.get("n_reviews", 1) or 1))} for t in th if isinstance(t, dict) and t.get("theme")][:8]


JUDGE = """List A = themes real users raised about a product. List B = candidate themes.
For each item in A, say whether some item in B substantially covers the same point (same concern/praise/question/request,
not merely the same broad area). For each item in B, say whether it substantially matches some item in A.
Return JSON {{"a_covered": [true/false per A item], "b_present": [true/false per B item]}}.
A:
{a}
B:
{b}"""
def judge(real, cand):
    a = gem(JUDGE.format(a="\n".join(f"{k+1}. {t['theme']}" for k, t in enumerate(real)), b="\n".join(f"{k+1}. {t}" for k, t in enumerate(cand))), 0.0, 800)
    if not isinstance(a, dict): return None
    ac, bp = a.get("a_covered", []), a.get("b_present", [])
    return ([bool(x) for x in ac], [bool(x) for x in bp]) if len(ac) == len(real) and len(bp) == len(cand) else None


VARS = ["U0_launch", "U1_postuse", "U2_postuse_R"]; N = len(prods)
with cf.ThreadPoolExecutor(8) as ex:
    list(ex.map(lambda i: [run(f"truth|{prods[i]['slug']}", lambda: truth(i))] + [run(f"{v}|{prods[i]['slug']}", lambda v=v: gen(i, v)) for v in VARS], range(N)))
json.dump(C, open(cache_f, "w")); print("generated usd", round(USD["usd"], 3), flush=True)
T = {i: C[f"truth|{prods[i]['slug']}"] for i in range(N) if C.get(f"truth|{prods[i]['slug']}")}
cands = {v: {i: C.get(f"{v}|{prods[i]['slug']}") for i in range(N)} for v in VARS}
texts = sorted({t["theme"] for v in T.values() for t in v}); TE = embed(texts); tix = {t: k for k, t in enumerate(texts)}
cands["GENERIC_CATEGORY"], cands["SHUFFLE_CATEGORY"] = {}, {}
for i in range(N):
    pool = [t["theme"] for o, v in T.items() if o != i and cl[o] == cl[i] for t in v] or [t["theme"] for o, v in T.items() if o != i for t in v]
    M = TE[[tix[t] for t in pool]]; cands["GENERIC_CATEGORY"][i] = [pool[k] for k in np.argsort(-(M @ M.T).mean(1))[:6]]
    oth = [o for o in range(N) if o != i and cl[o] == cl[i] and cands["U1_postuse"].get(o)] or [o for o in range(N) if o != i and cands["U1_postuse"].get(o)]
    cands["SHUFFLE_CATEGORY"][i] = cands["U1_postuse"][random.Random(i).choice(oth)]
jobs = [(v, i) for v in cands for i in range(N) if T.get(i) and cands[v].get(i)]; random.Random(1).shuffle(jobs)
key = lambda v, i: f"judge|{v}|{hashlib.md5(json.dumps(cands[v][i]).encode()).hexdigest()[:10]}|{prods[i]['slug']}"
with cf.ThreadPoolExecutor(8) as ex: J = dict(zip(jobs, ex.map(lambda j: run(key(*j), lambda: judge(T[j[1]], cands[j[0]][j[1]])), jobs)))
json.dump(C, open(cache_f, "w"))
rows = []
for (v, i), jr in J.items():
    if not jr: continue
    ac, bp = np.array(jr[0]), np.array(jr[1]); ty = np.array([t["type"] for t in T[i]])
    pr = np.isin(ty, ["praise"]); cm = np.isin(ty, ["complaint", "missing_feature"])
    rows.append({"v": v, "i": i, "recall": ac.mean(), "precision": bp.mean(), "recall_praise": ac[pr].mean() if pr.any() else np.nan,
                 "recall_complaint": ac[cm].mean() if cm.any() else np.nan})
D = pd.DataFrame(rows); MET = ["recall", "precision", "recall_praise", "recall_complaint"]
P_ = D.pivot_table(index="i", columns="v", values=MET)


def boot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]


res = {"design": __doc__.split("\n    python")[0], "products": N, "reviews_used": int(sum(min(40, len(p["reviews"])) for p in prods)),
       "truth_types": pd.Series([t["type"] for v in T.values() for t in v]).value_counts().to_dict(), "means": {}, "paired": {}}
for v in cands: res["means"][v] = {m: boot(P_[(m, v)]) for m in MET if (m, v) in P_}
for a, b in (("U1_postuse", "GENERIC_CATEGORY"), ("U1_postuse", "SHUFFLE_CATEGORY"), ("U0_launch", "GENERIC_CATEGORY"), ("U0_launch", "SHUFFLE_CATEGORY"),
             ("U2_postuse_R", "U1_postuse"), ("U1_postuse", "U0_launch"), ("U2_postuse_R", "GENERIC_CATEGORY")):
    res["paired"][f"{a} - {b}"] = {m: boot(P_[(m, a)] - P_[(m, b)]) for m in MET if (m, a) in P_ and (m, b) in P_}
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "reviews_eval.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1))
