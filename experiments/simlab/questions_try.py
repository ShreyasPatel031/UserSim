"""Raise the /try "They would question" list (orchestrator 08:35Z Nov 12). Fresh Oct 27 - Nov 10 launches read through the site's code
(try_fixes cache: page read + raw excerpt; try_e2e cache: the page read's "doubts" = what /try shows now), identity-free truth from the
API comment snapshots (maker = first top-level author), launches with >= 3 real questions (>= 3 critical themes for concerns).
Lists (top 3 judged):
  CURRENT    the page read's "doubts" (current /try list)
  GENERIC    the most frequent question themes across all retrieval-bundle launches (no product information)
  RETR       question themes of the 10 most similar EARLIER launches (reactions_retrieval_v1, paraphrased, no verbatim comments),
             clustered at cosine >= 0.80 and ranked by how many neighbours raised them (no LLM)
  RETR+LLM   gemini-2.5-flash picks and orders the 5 most likely from the RETR candidates (top 15) given the raw page excerpt, adapting
             wording to this product
  RANKED     the try_fixes RANKED recipe from the raw excerpt (generator + retrieval + likelihood), re-judged here on the same truth
Concerns: the same with objection / question / feature-request themes. Judges as concerns_rank / questions_rank (gemini-2.5-flash,
blinded); a second, differently worded judge on a 30-launch subsample. p@3 / hit@3, launch bootstrap, paired vs CURRENT and RANKED.
    python questions_try.py <scratchpad> <out dir>
"""
import glob, json, os, re, subprocess, sys, time, urllib.request, html as _html
import concurrent.futures as cf
import numpy as np, pandas as pd

SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
GEN = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/gemini-2.5-flash:generateContent"
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
_tk = {"t": "", "at": 0}; USD = {"usd": 0.0}
def token():
    if time.time() - _tk["at"] > 300: _tk["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tk["at"] = time.time()
    return _tk["t"]
def post(url, body):
    for i in range(6):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), {"Authorization": "Bearer " + token(), "Content-Type": "application/json"}), timeout=180))
        except Exception: time.sleep(3 * (i + 1))  # noqa: BLE001
def gem(prompt, tok=1200, temp=0.0):
    j = post(GEN, {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": temp, "maxOutputTokens": tok, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}})
    if not j: return {}
    u = j.get("usageMetadata", {}); USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * 0.30 + u.get("candidatesTokenCount", 0) / 1e6 * 2.50
    try: return json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"]))
    except Exception: return {}  # noqa: BLE001
def embed(texts):
    out = []
    for i in range(0, len(texts), 200):
        j = post(EMB, {"instances": [{"content": t[:1200], "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]], "parameters": {"outputDimensionality": 256}})
        out.append(np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32))
    E = np.vstack(out); return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)
cache_f = os.path.join(OUT, "cache.json"); K = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(key, fn):
    if key not in K or K[key] is None: K[key] = fn()
    return K[key]
tb = lambda x: x if isinstance(x, bool) else str(x).strip().lower() in ("true", "yes", "1")
num = lambda l: "\n".join(f"{k+1}. {str(t)[:300]}" for k, t in enumerate(l))

# ---------- data ----------
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); byid = {r.id: r for r in L.itertuples()}
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
FK = json.load(open(os.path.join(SP, "try_fixes/cache.json"))); EK = json.load(open(os.path.join(SP, "try_e2e/full/cache.json")))
reads = {k.split("|", 1)[1]: v["read"] for k, v in FK.items() if k.startswith("p|") and "read" in v}
doubts = {k.split("|", 1)[1]: (v.get("page") or {}).get("doubts") or [] for k, v in EK.items() if k.startswith("run|") and v.get("page")}
S = [i for i in reads if len(truth_c.get(i, [])) >= 5 and i in byid]
print("launches with read + >= 5 truth comments", len(S), "with current doubts", sum(i in doubts for i in S), flush=True)
RBE = np.load(os.path.join(SP, "rbundle/reactions_retrieval_v1.npz"))["emb"].astype(np.float32); RBM = json.load(open(os.path.join(SP, "rbundle/reactions_retrieval_v1.json")))
QRE = re.compile(r"^\s*question\s*:\s*", re.I); CRE = re.compile(r"^\s*(objection|question|feature request|feature_request)\s*:\s*", re.I)
TH = {"q": [[QRE.sub("", t) for t in m["themes"] if QRE.match(t)] for m in RBM], "c": [[CRE.sub("", t) for t in m["themes"] if CRE.match(t)] for m in RBM]}
allq = sorted({t for v in TH["q"] + TH["c"] for t in v}); ef = os.path.join(OUT, "theme_emb.npy")
TE_ = np.load(ef) if os.path.exists(ef) and len(np.load(ef)) == len(allq) else embed(allq); np.save(ef, TE_); tix = {t: i for i, t in enumerate(allq)}


def freq(rows, kind, k_out, min_cos=0.80):
    items = [(t, r) for r in rows for t in TH[kind][r]]
    if not items: return []
    X = TE_[[tix[t] for t, _ in items]]; SS = X @ X.T; own = np.array([r for _, r in items]); cnt = np.array([len(set(own[SS[i] >= min_cos])) for i in range(len(items))])
    out, used = [], np.zeros(len(items), bool)
    for i in np.argsort(-cnt):
        if used[i]: continue
        out.append(items[i][0]); used |= SS[i] >= min_cos
        if len(out) == k_out: break
    return out


GENERIC = {kd: freq(list(rng.choice(len(RBM), 600, replace=False)), kd, 5) for kd in ("q", "c")}
QE = embed([f"{reads[i].get('name')}. {reads[i].get('tagline')}. {(reads[i].get('summary') or '')} {(reads[i].get('page_excerpt') or '')[:600]}" for i in S])
PICK = """A new product is launching on Product Hunt today. Below is text from its own web page, then candidate {what} that users of
SIMILAR past launches raised. Choose the 5 that real users are most likely to raise for THIS product, most likely first; adapt the
wording to this product, but do not invent features. You may only use the candidates.
Product: {name} - {tagline}
Page text:
{excerpt}
Candidates:
{c}
Return JSON {{"items": ["...", ...]}}"""
EX = """Below are real user comments on a product launch (makers' own comments removed). Return JSON with two lists:
"critical": ONLY critical themes (objections/concerns, doubting questions, feature requests), at most 6, most frequent first;
"questions": ONLY questions users asked the makers, at most 6, most frequent first.
Comments:
{c}"""
JQ = """List A = questions real users asked the makers of a product launch. List B = a ranked list of predicted questions or
reactions. For each item in B, does it substantially match some question in A (asks for the same specific thing, not merely the
same broad area)? Return JSON {{"b_matches": [true/false per B item]}}
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
J2 = """You are checking a forecast of what users would say in launch comments.
REAL: points real users actually made ({what}).
FORECAST: three predicted points.
For each FORECAST point answer true only if one REAL point makes essentially the same specific point (not just the same topic).
Return JSON {{"hits": [true/false, true/false, true/false]}}
REAL:
{a}
FORECAST:
{b}"""


def judge(JP, truth, lst, key):
    if not truth or not lst: return None
    bm = run(key, lambda: (gem(JP.format(a=num(truth), b=num(lst[:3])), 300)).get("b_matches"))
    bm = [tb(x) for x in bm] if isinstance(bm, list) else None
    return (float(np.mean(bm)), float(any(bm))) if bm and len(bm) == len(lst[:3]) else None


def judge2(what, truth, lst, key):
    if not truth or len(lst) < 3: return None
    h = run(key, lambda: (gem(J2.format(what=what, a=num(truth), b=num(lst[:3])), 200)).get("hits"))
    h = [tb(x) for x in h] if isinstance(h, list) else None
    return (float(np.mean(h)), float(any(h))) if h and len(h) == 3 else None


# RANKED lists from try_fixes are not cached as lists; rebuild them with the same function (imported from try_fixes would need
# the site worktree), so RANKED is approximated by try_fixes' judged values only where comparable: here we re-generate the
# questions generator + retrieval + likelihood inline (same prompts as try_fixes).
QG = """A new product is launching on Product Hunt today.
Product: {name} - {tagline}
Description: {desc}
List the 6 questions users are most likely to ask the makers in the launch comments in the first hours, most likely first.
Be specific to this product; do not invent features. Return JSON {{"questions": ["...", ...]}}"""
DCAT = ("List the 6 criticisms most likely from real users: first the complaints users of this product CATEGORY almost always raise (2-3), then the "
        "ones SPECIFIC to this product (the rest). Write them as they would appear in launch-day comments (objections, questions to the maker, feature requests). Do not invent features.\n"
        "Product: {name}\nDescription: {desc}\nReturn JSON {{\"criticisms\": [\"<one specific sentence>\", ...]}}")
LIKE = """A new product is launching on Product Hunt.
Product: {name} - {tagline}
Description: {desc}
Below are candidate {what} users might raise in the launch comments.
Rate how likely real users are to raise each one for THIS product, 1 (unlikely) to 5 (very likely).
Return JSON {{"ratings": [1-5 per candidate, in order]}}
{c}"""


def work(qi):
    i = S[qi]; rd = reads[i]; name, tag, exc = rd.get("name") or "", rd.get("tagline") or "", rd.get("page_excerpt") or ""; day = byid[i].day
    T = run(f"truth|{i}", lambda: gem(EX.format(c="\n".join(f"- {t[:400]}" for t in truth_c[i][:40])), 1500)); tq, tc = (T.get("questions") or [])[:6], (T.get("critical") or [])[:6]
    sims = RBE @ QE[qi]; nb = [j for j in np.argsort(-sims) if RBM[j]["day"] < day][:25]; nb10 = nb[:10]
    out = {"id": i, "n_q": len(tq), "n_c": len(tc)}
    for kd, truth, JP, what in (("q", tq, JQ, "questions to the makers"), ("c", tc, JC, "concerns (objections, doubting questions, feature requests)")):
        retr = freq(nb10, kd, 15); retr25 = freq(nb, kd, 8)
        pick = run(f"pick|{kd}|{i}", lambda: [str(x) for x in (gem(PICK.format(what=what, name=name, tagline=tag, excerpt=exc[:1500], c=num(retr)), 800, 0.2).get("items") or [])][:5]) if retr else []
        gen = run(f"gen|{kd}|{i}", lambda: [str(x) for x in (gem((QG if kd == "q" else DCAT).format(name=(name if kd == "q" else f"{name} - {tag}"), tagline=tag, desc=exc[:1500]), 1200, 0.3).get("questions" if kd == "q" else "criticisms") or [])][:6])
        cands = gen + retr25
        if cands:
            X = embed(cands) if f"rk|{kd}|{i}" not in K else None
            if X is not None:
                NX = TE_[[tix[t] for j in nb for t in TH[kd][j]]] if any(TH[kd][j] for j in nb) else np.zeros((0, 256), np.float32)
                own = np.array([j for j in nb for _ in TH[kd][j]]); g = np.array(["G"] * len(gen) + ["R"] * len(retr25)); SS = X @ X.T
                a = np.array([len(set(own[(NX @ X[k]) >= 0.80])) if len(NX) else 0 for k in range(len(cands))], float); b = np.array([((SS[k] >= 0.80) & (g != g[k])).sum() for k in range(len(cands))], float)
                lk = gem(LIKE.format(name=name, tagline=tag, desc=exc[:1200], what=what, c=num(cands)), 300).get("ratings"); c_ = np.array(lk if isinstance(lk, list) and len(lk) == len(cands) else [3] * len(cands), float)
                rk = lambda v: pd.Series(v).rank(pct=True).to_numpy(); sc = (rk(a) + rk(b) + rk(c_)) / 3; lst, used = [], np.zeros(len(cands), bool)
                for k in np.argsort(-sc):
                    if used[k]: continue
                    lst.append(cands[k]); used |= SS[k] >= 0.90
                    if len(lst) == 5: break
                K[f"rk|{kd}|{i}"] = lst
        ranked = K.get(f"rk|{kd}|{i}") or []
        lists = {"CURRENT": doubts.get(i, []) if kd == "q" else doubts.get(i, []), "GENERIC": GENERIC[kd], "RETR": retr[:5], "RETR+LLM": pick, "RANKED": ranked}
        for m, lst in lists.items():
            out[f"{kd}|{m}"] = judge(JP, truth, lst, f"j|{kd}|{m}|{i}")
            if qi < 30: out[f"{kd}|{m}|j2"] = judge2(what, truth, lst, f"j2|{kd}|{m}|{i}")
    return out


with cf.ThreadPoolExecutor(6) as ex: R = list(ex.map(work, range(len(S))))
json.dump(K, open(cache_f, "w"))


def mb(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]
M = ["CURRENT", "GENERIC", "RETR", "RETR+LLM", "RANKED"]
res = {"design": __doc__.split("\n    python")[0], "launches": len(S), "usd": None}
for kd, nmin, lab in (("q", 3, "questions"), ("c", 3, "concerns")):
    sub = [r for r in R if r[f"n_{kd}"] >= nmin]; g = lambda m, j, suf="": np.array([(r.get(f"{kd}|{m}{suf}") or [np.nan, np.nan])[j] for r in sub], float)
    d = {"launches": len(sub)}
    for m in M: d[m] = {"p3": mb(g(m, 0)), "hit3": mb(g(m, 1)), "p3 second judge (first 30)": mb(g(m, 0, "|j2"))}
    for m in ("RETR", "RETR+LLM", "RANKED"):
        d[f"{m} - CURRENT (paired)"] = {"p3": mb(g(m, 0) - g("CURRENT", 0)), "hit3": mb(g(m, 1) - g("CURRENT", 1))}
    for m in ("RETR", "RETR+LLM"):
        d[f"{m} - RANKED (paired)"] = {"p3": mb(g(m, 0) - g("RANKED", 0)), "hit3": mb(g(m, 1) - g("RANKED", 1))}
    res[lab] = d
res["usd"] = round(USD["usd"], 3); res["generic_lists"] = GENERIC
json.dump(res, open(os.path.join(OUT, "questions_try.json"), "w"), indent=1, default=str)
for lab in ("questions", "concerns"):
    print("==", lab, res[lab]["launches"])
    for k, v in res[lab].items():
        if k != "launches": print(" ", k, v)
print("usd", res["usd"])
