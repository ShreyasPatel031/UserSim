"""Raise complaint recall and control for memorisation (orchestrator 23:45Z Nov 11).
Part A - reviews (the 228 products of reviews_eval.py; truth themes, U1 outputs and controls reused from its cache).
  Candidate list = U1 (post-use prompt, 6 comments) + a critic pass (gemini-2.5-flash, temperature 0.3) of K items:
    A_critic     objections, deal-breakers, missing features, pricing and trust concerns (K = 6)
    B_retrieval  A + complaint/missing-feature themes from the reviews of the 5 most similar OTHER products (gemini
                 embedding; same slug stem and themes naming the target are dropped). Neighbour themes come from those
                 products' full review sets (not date-restricted: they are other products' reviews).
    C_viewpoints critic voices: skeptic, churned user, competitor's user (K = 6)
    D_category   the complaints users of this product category always raise + the ones specific to this product (K = 6)
    E_more10     A with K = 10
  Complaint judge (blinded): A = the product's complaint + missing-feature truth themes; B = the candidate list; returns
  a_covered, and per B item is_criticism and matches. complaint recall = share of A covered; complaint precision = share of
  criticism items that match. Overall recall/precision with the reviews_eval judge on all truth themes.
  Memorisation: first review >= 2025-01-01 (after the model's Jan 2025 cutoff; 11 products, indicative) vs earlier.
Part B - clean slice: the 300 launches of reactions_eval (Aug-Oct 2026, all after the cutoff). Truth = critical themes only
  (objections, questions, feature requests) from the real non-team comments (separate flash pass). Candidates: BEST (the
  deployed launch reactions, cached in reactions_v2) vs BEST + the winning critic pass (launch framing). Same complaint judge.
Paired differences vs U1 (A) / BEST (B), bootstrap 95% CIs; cost and latency per request.
    python complaints_eval.py <reviews_eval out dir> <competitor_reviews.jsonl.gz> <uses2 export> <react_v2 dir> <cf dir> <launches dir> <out dir> [winner]
"""
import concurrent.futures as cf, glob, gzip, hashlib, html, json, os, random, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd

RE_, REV, EXP, RV2, CFD, LDIR, OUT = sys.argv[1:8]; WIN = sys.argv[8] if len(sys.argv) > 8 else None
os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
GEN = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/gemini-2.5-flash:generateContent"
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
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
            print("retry", i, str(e)[:100], flush=True); time.sleep(4 * (i + 1))
    return None


def gem(prompt, temp=0.0, maxtok=2500, tag=None):
    t0 = time.time()
    j = post(GEN, {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                   "generationConfig": {"temperature": temp, "maxOutputTokens": maxtok, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}})
    if tag: LAT.setdefault(tag, []).append(time.time() - t0)
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


cache_f = os.path.join(OUT, "cache.json"); C = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
def run(key, fn):
    if key not in C: C[key] = fn()
    return C[key]
RC = json.load(open(os.path.join(RE_, "cache.json")))           # reviews_eval cache: truth|slug, U1_postuse|slug

# ---------- Part A data (same product list as reviews_eval)
P = pd.read_parquet(os.path.join(EXP, "products.parquet")); card = dict(zip(P.slug, P.rich_text.fillna(P.text)))
prods = []
for line in gzip.open(REV):
    r = json.loads(line)
    if str(r["status"]) != "200": continue
    rv = r["reviews"] if isinstance(r["reviews"], list) else json.loads(r["reviews"])
    if len(rv) >= 10 and r["slug"] in card:
        prods.append({"slug": r["slug"], "name": r["competitor"], "card": card[r["slug"]], "first": min(v["date"] for v in rv if v.get("date"))})
T = {p["slug"]: RC.get(f"truth|{p['slug']}") or [] for p in prods}
TC = {s: [t for t in v if t["type"] in ("complaint", "missing_feature")] for s, v in T.items()}
U1 = {p["slug"]: RC.get(f"U1_postuse|{p['slug']}") for p in prods}
E = embed([p["card"][:1500] for p in prods]); stem = lambda s: re.sub(r"-\d+$", "", s)
print("products", len(prods), "with complaint truth", sum(bool(v) for v in TC.values()), "clean (first review >= 2025)", sum(p["first"] >= "2025-01-01" for p in prods), flush=True)

CRIT = {"A_critic": "List the {k} most likely criticisms real users raise about this product after using it: objections, deal-breakers, missing features, pricing concerns and trust/privacy concerns. Be specific to this product; do not invent features.",
        "C_viewpoints": "Write {k} criticisms of this product from three viewpoints (two each): a skeptic evaluating it, a user who churned after trying it, and a user of a competing product explaining why they did not switch. Be specific; do not invent features.",
        "D_category": "List the {k} criticisms most likely from real users: first the complaints users of this product CATEGORY almost always raise (2-3), then the ones SPECIFIC to this product (the rest). Do not invent features.",
        "E_more10": "List the {k} most likely criticisms real users raise about this product after using it: objections, deal-breakers, missing features, pricing concerns and trust/privacy concerns. Be specific to this product; do not invent features."}
KOF = {"A_critic": 6, "B_retrieval": 6, "C_viewpoints": 6, "D_category": 6, "E_more10": 10}
CRIT["B_retrieval"] = CRIT["A_critic"]
TAIL = """
Product: {name}
Description: {desc}
{ground}
Return JSON {{"criticisms": ["<one specific sentence>", ...]}}"""


def critic(i, v, framing="post"):
    p = prods[i] if isinstance(i, int) else i
    ground = ""
    if v == "B_retrieval":
        s = E @ E[prods.index(p)]; th = []
        for j in np.argsort(-s):
            o = prods[j]
            if o["slug"] == p["slug"] or stem(o["slug"]) == stem(p["slug"]): continue
            th += [t["theme"] for t in TC.get(o["slug"], []) if p["name"].lower() not in t["theme"].lower()]
            if len([1 for _ in th]) >= 15 or j is None: pass
            if sum(1 for o2 in [o]) and len(th) >= 15: break
        ground = "Users of similar OTHER products complained about (reuse only what plausibly applies here):\n" + "\n".join(f"- {t}" for t in th[:15])
    pre = CRIT[v].format(k=KOF[v])
    if framing == "launch": pre = pre.replace("after using it", "in launch-day comments (objections, questions to the maker, feature requests)")
    a = gem(pre + TAIL.format(name=p["name"], desc=p["card"][:1500], ground=ground), 0.3, 1500, tag=v)
    return [str(x) for x in ((a or {}).get("criticisms") or [])][:KOF[v]]


CJ = """List A = criticisms real users raised about a product (complaints, missing features). List B = candidate statements.
For each item in A: is it substantially covered by some item in B (same specific concern, not merely the same broad area)?
For each item in B: is it a criticism/concern/request (true) or praise/neutral (false); and does it substantially match some item in A?
Return JSON {{"a_covered": [true/false per A item], "b_is_criticism": [true/false per B item], "b_matches": [true/false per B item]}}.
A:
{a}
B:
{b}"""


def cjudge(real, cand):
    a = gem(CJ.format(a="\n".join(f"{k+1}. {t}" for k, t in enumerate(real)), b="\n".join(f"{k+1}. {t}" for k, t in enumerate(cand))), 0.0, 1200)
    if not isinstance(a, dict): return None
    ac, bc, bm = a.get("a_covered", []), a.get("b_is_criticism", []), a.get("b_matches", [])
    return (ac, bc, bm) if len(ac) == len(real) and len(bc) == len(cand) == len(bm) else None


def cscore(truth_lists, cands, tag):
    keys = [k for k in cands if truth_lists.get(k) and cands.get(k)]
    def one(k):
        return k, run(f"cj|{tag}|{hashlib.md5(json.dumps(cands[k]).encode()).hexdigest()[:10]}|{k}", lambda: cjudge(truth_lists[k], cands[k]))
    with cf.ThreadPoolExecutor(8) as ex: J = dict(ex.map(one, keys))
    rec, pre, ncrit = {}, {}, {}
    for k, jr in J.items():
        if not jr: continue
        ac, bc, bm = (np.array(x, bool) for x in jr)
        rec[k] = ac.mean(); ncrit[k] = bc.sum(); pre[k] = (bm & bc).sum() / bc.sum() if bc.sum() else np.nan
    return pd.DataFrame({"c_recall": rec, "c_precision": pre, "n_criticism_items": ncrit})


def boot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]


res = {"design": __doc__.split("\n    python")[0], "partA": {}, "partB": {}}
TCl = {p["slug"]: [t["theme"] for t in TC[p["slug"]]] for p in prods}
D0 = cscore(TCl, U1, "U1"); res["partA"]["U1"] = {m: boot(D0[m]) for m in ("c_recall", "c_precision")}
clean = {p["slug"] for p in prods if p["first"] >= "2025-01-01"}
VARS = ["A_critic", "B_retrieval", "C_viewpoints", "D_category", "E_more10"]
for v in VARS:
    with cf.ThreadPoolExecutor(8) as ex:
        crit = dict(zip([p["slug"] for p in prods], ex.map(lambda i: run(f"crit|{v}|{prods[i]['slug']}", lambda: critic(i, v)), range(len(prods)))))
    merged = {s: (U1[s] or []) + (crit[s] or []) for s in U1}
    D = cscore(TCl, merged, v); Dc = cscore(TCl, crit, v + "_only"); j = D.index.intersection(D0.index)
    r = {"merged": {m: boot(D[m]) for m in ("c_recall", "c_precision")}, "critic_only": {m: boot(Dc[m]) for m in ("c_recall", "c_precision")},
         "merged - U1 (paired)": {m: boot(D.loc[j, m] - D0.loc[j, m]) for m in ("c_recall", "c_precision")},
         "median_critic_latency_s": round(float(np.median(LAT.get(v, [0]))), 2)}
    jc = [s for s in j if s in clean]; jn = [s for s in j if s not in clean]
    r["memorisation split, merged - U1 c_recall"] = {"clean (first review >= 2025)": boot(D.loc[jc, "c_recall"] - D0.loc[jc, "c_recall"]),
                                                    "pre-cutoff": boot(D.loc[jn, "c_recall"] - D0.loc[jn, "c_recall"])}
    res["partA"][v] = r; print(v, json.dumps(r)[:400], flush=True)
    json.dump(C, open(cache_f, "w")); res["usd"] = round(USD["usd"], 3); json.dump(res, open(os.path.join(OUT, "complaints_eval.json"), "w"), indent=1)
res["partA"]["U1 memorisation split c_recall"] = {"clean": boot(D0.loc[[s for s in D0.index if s in clean], "c_recall"]), "pre-cutoff": boot(D0.loc[[s for s in D0.index if s not in clean], "c_recall"])}

# ---------- Part B: post-cutoff launches, critical themes only
if WIN:
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
    CT = """Below are real user comments on a product launch (makers' own comments removed). Extract ONLY the critical themes:
objections/concerns, questions that imply doubt or a gap, and feature requests. Ignore praise and congratulations.
Return JSON {{"themes": ["<one specific sentence>", ...]}} with at most 6 themes, most frequent first (empty list if none).
Comments:
{c}"""
    TB = {s: run(f"ctruth|{s}", lambda s=s: (gem(CT.format(c="\n".join(f"- {t[:400]}" for t in list(com[s].values())[:40])), 0.0, 1200) or {}).get("themes") or []) for s in S}
    RV = json.load(open(os.path.join(RV2, "cache_v2.json"))); BEST = {s: RV.get(f"gen|BEST|{s}") for s in S}
    with cf.ThreadPoolExecutor(8) as ex:
        critB = dict(zip(S, ex.map(lambda s: run(f"critB|{WIN}|{s}", lambda: critic({"slug": s, "name": bys[s].name, "card": f"{bys[s].name}. {bys[s].tagline}. {(bys[s].description or '')[:1300]}"}, WIN if WIN != "B_retrieval" else "A_critic", "launch")), S)))
    mergedB = {s: (BEST[s] or []) + (critB[s] or []) for s in S}
    B0 = cscore(TB, BEST, "B_BEST"); B1 = cscore(TB, mergedB, "B_merged"); j = B0.index.intersection(B1.index)
    res["partB"] = {"launches_with_critical_truth": int(sum(bool(v) for v in TB.values())), "BEST": {m: boot(B0[m]) for m in ("c_recall", "c_precision")},
                    f"BEST + {WIN} critic": {m: boot(B1[m]) for m in ("c_recall", "c_precision")},
                    "diff (paired)": {m: boot(B1.loc[j, m] - B0.loc[j, m]) for m in ("c_recall", "c_precision")}}
    print("partB", res["partB"], flush=True)
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "complaints_eval.json"), "w"), indent=1); json.dump(C, open(cache_f, "w"))
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1))
