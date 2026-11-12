"""Tone of reception: can we predict the share of critical / questioning comments? (orchestrator, Nov 12)
Truth per launch (identity-free: the first top-level comment's author and the hunter removed; top-level comments only): one
gemini-2.5-flash-lite call labels each comment critical / question / praise / congrats / other -> shares; number of distinct commenters.
Launch sets: S300 (the reactions sample, Aug-Oct 2026, PH thread dumps; PH-description input) and FRESH (Oct 27 - Nov 10 page reads
with >= 5 top-level comments in the API snapshots; page and PH input).
Predictions: (a) SIM: the same classifier on the simulated reactions (S300: BEST; FRESH: the site's reactions from page / PH input);
(b) DIRECT: one gemini-2.5-flash call estimating the shares from the product text; (c) RETR: mean real mix of the 10 most similar
earlier S300 launches (gemini embedding of PH text); (d) CONST: mean of earlier launches; CAT: mean of earlier launches with the same
first topic (>= 5, else CONST). S300 is evaluated month-forward on Sep-Oct (Aug = history only); FRESH uses all S300 as history.
Metrics: Spearman and MAE (percentage points) of predicted vs real critical share and question share with launch-bootstrap CIs;
"contested" lift = share of launches in the predicted top quartile of critical share that are in the real top quartile / 0.25;
pooled Spearman of real and predicted critical share with final daily rank.
Part 4: the reactions themes claim vs a CONSTANT theme list (the 8 most frequent themes of Aug launches, frequency-clustered at
cosine 0.80), judged with the reactions_eval judge against the same truth themes as BEST, on Sep-Oct S300 launches; paired.
    python tone_eval.py <scratchpad> <out dir>
"""
import concurrent.futures as cf, glob, gzip, html as _html, json, os, re, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd
from scipy.stats import spearmanr

SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
URL = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/{m}:generateContent"
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-flash-lite": (0.10, 0.40)}; USD = {"usd": 0.0}; _tk = {"t": "", "at": 0}
def token():
    if time.time() - _tk["at"] > 300: _tk["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tk["at"] = time.time()
    return _tk["t"]
def post(url, body):
    for i in range(6):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), {"Authorization": "Bearer " + token(), "Content-Type": "application/json"}), timeout=180))
        except Exception: time.sleep(3 * (i + 1))  # noqa: BLE001
def gem(prompt, model="gemini-2.5-flash-lite", tok=1500):
    j = post(URL.format(m=model), {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0, "maxOutputTokens": tok, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}})
    if not j: return {}
    u = j.get("usageMetadata", {}); pi, po = PRICE[model]; USD["usd"] += u.get("promptTokenCount", 0) / 1e6 * pi + u.get("candidatesTokenCount", 0) / 1e6 * po
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
    if key not in K or not K[key]: K[key] = fn()
    return K[key]
clean = lambda t: re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
num = lambda l: "\n".join(f"{k+1}. {str(t)[:300]}" for k, t in enumerate(l))
CATS = ["critical", "question", "praise", "congrats", "other"]
LAB = """Label each comment on a product launch with exactly one of: "critical" (objection, doubt, complaint, concern, feature
request), "question" (a question to the makers that is not doubtful), "praise" (specific positive point), "congrats" (generic
congratulations / good luck / upvoted, nothing specific), "other". Return JSON {{"labels": ["...", ...]}} with one label per comment.
Comments:
{c}"""
DIRECT = """A product is launching on Product Hunt today.
Product: {name} - {tagline}
Description: {desc}
Estimate the share of launch-day top-level comments (not from the makers) that will be: critical (objections, doubts, complaints,
feature requests), question (non-doubtful questions to the makers), praise (specific positives), congrats (generic congratulations).
Return JSON {{"critical": 0-1, "question": 0-1, "praise": 0-1, "congrats": 0-1}} (shares of all comments)."""


def mix(texts, key):
    if len(texts) == 0: return None
    lab = run(key, lambda: (gem(LAB.format(c=num(texts[:40]))) or {}).get("labels"))
    if not isinstance(lab, list) or not lab: return None
    lab = [str(x).lower() for x in lab]; return {c: float(np.mean([x == c for x in lab])) for c in CATS}


L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna()].copy(); L["id"] = L.id.astype(str); bys = {s: r for s, r in zip(L.slug, L.itertuples())}; byid = {r.id: r for r in L.itertuples()}
RS = json.load(open(os.path.join(SP, "react_site/cache_site.json"))); S300 = sorted(k.split("|", 1)[1] for k in RS if k.startswith("truth|") and k.split("|", 1)[1] in bys)
RV = json.load(open(os.path.join(SP, "react_v2/cache_v2.json")))
top = {}
need = set(S300)
for f in sorted(glob.glob(os.path.join(SP, "cf/page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in need: continue
        tl = [(n["node"].get("createdAt") or "", ((n["node"].get("user") or {}).get("username") or "").lower(), clean(n["node"].get("bodyHtml"))) for n in ((p_.get("threads") or {}).get("edges") or [])]
        top[p_["slug"]] = tl
truth300 = {}
for s in S300:
    tl = sorted(top.get(s, [])); r = bys[s]
    if not tl: continue
    first = tl[0][1]; hunter = str(r.poster or "").lower(); keep = [t for _, u, t in tl if u not in (first, hunter) and len(t) > 15]
    if len(keep) >= 5: truth300[s] = (keep, len({u for _, u, t in tl if u not in (first, hunter)}))
C = {}
for f in glob.glob(os.path.join(SP, "try_e2e/apic/*/*.jsonl")):
    for l in open(f): x = json.loads(l); C[x["comment_id"]] = x
byp = {}
for x in C.values(): byp.setdefault(str(x["post_id"]), []).append(x)
EK = json.load(open(os.path.join(SP, "try_e2e/full/cache.json")))
fresh = {}
for k, v in EK.items():
    if not k.startswith("run|"): continue
    i = k.split("|", 1)[1]; cs = sorted([c for c in byp.get(i, []) if not c.get("parentId")], key=lambda c: c["createdAt"])
    if not cs or i not in byid: continue
    first = cs[0]["commenter_user_id"]; keep = [clean(c["body"]) for c in cs if c["commenter_user_id"] != first and len(clean(c["body"])) > 15]
    if len(keep) >= 5: fresh[i] = {"truth": keep, "site": v.get("site_react") or [], "ph": v.get("ph_react") or [], "page": v.get("page") or {}}
print("S300 with >= 5 top-level comments", len(truth300), "fresh", len(fresh), flush=True)
# ---------- truth + predictions ----------
def work300(s):
    r = bys[s]; out = {"key": s, "day": r.day, "rank": float(r.daily_rank), "topic": (json.loads(r.topics) or ["none"])[0] if isinstance(r.topics, str) and r.topics.startswith("[") else "none"}
    out["real"] = mix(truth300[s][0], f"lab|real|{s}"); out["sim"] = mix(RV.get(f"gen|BEST|{s}") or [], f"lab|sim|{s}")
    out["direct"] = run(f"dir|ph|{s}", lambda: gem(DIRECT.format(name=r.name, tagline=r.tagline, desc=(r.description or "")[:1500]), "gemini-2.5-flash", 200)); out["id"] = r.id
    return out
def workf(i):
    v = fresh[i]; r = byid[i]; pg = v["page"]; out = {"key": i, "day": r.day, "rank": float(r.daily_rank), "topic": (json.loads(r.topics) or ["none"])[0] if isinstance(r.topics, str) and r.topics.startswith("[") else "none", "id": i}
    out["real"] = mix(v["truth"], f"lab|realf|{i}"); out["sim_page"] = mix(v["site"], f"lab|simp|{i}"); out["sim_ph"] = mix(v["ph"], f"lab|simph|{i}")
    out["direct_ph"] = run(f"dir|ph|{i}", lambda: gem(DIRECT.format(name=r.name, tagline=r.tagline, desc=(r.description or "")[:1500]), "gemini-2.5-flash", 200))
    if pg: out["direct_page"] = run(f"dir|page|{i}", lambda: gem(DIRECT.format(name=pg.get("name"), tagline=pg.get("tagline"), desc=(pg.get("summary") or "")), "gemini-2.5-flash", 200))
    return out
with cf.ThreadPoolExecutor(10) as ex: R3 = [x for x in ex.map(work300, list(truth300)) if x["real"]]
with cf.ThreadPoolExecutor(10) as ex: RF = [x for x in ex.map(workf, list(fresh)) if x["real"]]
json.dump(K, open(cache_f, "w")); print("labelled", len(R3), len(RF), "usd", round(USD["usd"], 3), flush=True)
LE = np.load(os.path.join(SP, "land/launch_emb256.npy")); Lv = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
Lv = Lv[Lv.daily_rank.notna() & Lv.votes.notna() & (Lv.day < "2026-11-11")].sort_values(["day", "id"]); Lv["id"] = Lv.id.astype(str); emb_of = {i: LE[k] for k, i in enumerate(Lv.id)}
H = pd.DataFrame([{"id": x["id"], "day": x["day"], "topic": x["topic"], **{f"r_{c}": x["real"][c] for c in CATS}} for x in R3])
def hist_preds(x, hist):
    h = hist[hist.day < x["day"][:7] + "-01"] if x["day"] < "2026-10-27" else hist
    if len(h) < 20: return None
    const = {c: h[f"r_{c}"].mean() for c in CATS}; hc = h[h.topic == x["topic"]]; cat = {c: (hc[f"r_{c}"].mean() if len(hc) >= 5 else const[c]) for c in CATS}
    ok = [i for i in h.id if i in emb_of]; e = emb_of.get(x["id"])
    retr = None
    if e is not None and len(ok) >= 10:
        E = np.vstack([emb_of[i] for i in ok]); nb = np.argsort(-(E @ e))[:10]; hh = h.set_index("id").loc[[ok[j] for j in nb]]; retr = {c: hh[f"r_{c}"].mean() for c in CATS}
    return const, cat, retr
def frame(R, sims, directs):
    rows = []
    for x in R:
        hp = hist_preds(x, H)
        if hp is None: continue
        const, cat, retr = hp; d = {"day": x["day"], "rank": x["rank"]}
        for c in ("critical", "question"):
            d[f"real_{c}"] = x["real"][c]; d[f"CONST_{c}"] = const[c]; d[f"CAT_{c}"] = cat[c]; d[f"RETR_{c}"] = retr[c] if retr else np.nan
            for s in sims: d[f"SIM_{s}_{c}"] = (x.get(s) or {}).get(c, np.nan)
            for s in directs:
                v = (x.get(s) or {}).get(c); d[f"DIRECT_{s}_{c}"] = float(v) if isinstance(v, (int, float)) else np.nan
        rows.append(d)
    return pd.DataFrame(rows)
def evaluate(F, label):
    out = {"launches": int(len(F))}
    preds = sorted({c.rsplit("_", 1)[0] for c in F.columns if c.endswith("_critical") and not c.startswith("real")})
    for c in ("critical", "question"):
        y = F[f"real_{c}"].values; out[f"real mean {c}"] = round(float(np.mean(y)) * 100, 1)
        for p in preds:
            v = F[f"{p}_{c}"].values; ok = ~np.isnan(v)
            if ok.sum() < 10: continue
            sp, mae = [], []
            for _ in range(2000):
                j = rng.choice(np.flatnonzero(ok), ok.sum()); sp.append(spearmanr(v[j], y[j]).correlation if np.std(v[j]) > 0 else 0); mae.append(np.mean(np.abs(v[j] - y[j])))
            out[f"{p} {c}"] = {"spearman": [round(float(spearmanr(v[ok], y[ok]).correlation), 3) if np.std(v[ok]) > 0 else 0.0] + [round(float(x), 3) for x in np.percentile(sp, [2.5, 97.5])],
                               "MAE_pp": [round(float(np.mean(np.abs(v[ok] - y[ok]))) * 100, 1)] + [round(float(x) * 100, 1) for x in np.percentile(mae, [2.5, 97.5])], "n": int(ok.sum())}
            if c == "critical" and np.std(v[ok]) > 0:
                q_p, q_r = np.percentile(v[ok], 75), np.percentile(y[ok], 75); sel = v[ok] >= q_p; out[f"{p} contested lift"] = round(float(np.mean(y[ok][sel] >= q_r) / 0.25), 2)
    out["real critical share vs -rank (pooled spearman)"] = round(float(spearmanr(F.real_critical, -F["rank"]).correlation), 3)
    for p in preds:
        v = F[f"{p}_critical"]
        if v.notna().sum() > 10 and v.std() > 0: out[f"{p} critical vs -rank"] = round(float(spearmanr(v[v.notna()], -F["rank"][v.notna()]).correlation), 3)
    return out
F3 = frame([x for x in R3 if x["day"] >= "2026-09-01"], ["sim"], ["direct"]); FF = frame(RF, ["sim_page", "sim_ph"], ["direct_ph", "direct_page"])
res = {"design": __doc__.split("\n    python")[0], "S300_sep_oct": evaluate(F3, "S300"), "fresh": evaluate(FF, "fresh"),
       "truth_mix_S300_mean": {c: round(float(np.mean([x["real"][c] for x in R3])) * 100, 1) for c in CATS}}
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1)[:6000], flush=True)
# ---------- part 4: constant theme list vs BEST ----------
JUDGE = """List A = themes real users raised about a product. List B = candidate themes.
For each item in A, say whether some item in B substantially covers the same point (same concern/praise/question/request,
not merely the same broad area). For each item in B, say whether it substantially matches some item in A.
Return JSON {{"a_covered": [true/false per A item], "b_present": [true/false per B item]}}.
A:
{a}
B:
{b}"""
tb = lambda x: x if isinstance(x, bool) else str(x).strip().lower() in ("true", "yes", "1")
aug = [s for s in S300 if bys[s].day < "2026-09-01"]; th = [(t["theme"], s) for s in aug for t in (RS.get(f"truth|{s}") or [])]
TE = embed([t for t, _ in th]); SS = TE @ TE.T; own = np.array([s for _, s in th]); cnt = np.array([len(set(own[SS[i] >= 0.80])) for i in range(len(th))])
CONST, used = [], np.zeros(len(th), bool)
for i in np.argsort(-cnt):
    if used[i]: continue
    CONST.append(th[i][0]); used |= SS[i] >= 0.80
    if len(CONST) == 8: break
def jrp(real, cand, key):
    if not real or not cand: return None
    a = run(key, lambda: gem(JUDGE.format(a=num([t["theme"] for t in real]), b=num(cand)), "gemini-2.5-flash", 800))
    ac, bp = [tb(x) for x in (a or {}).get("a_covered", [])], [tb(x) for x in (a or {}).get("b_present", [])]
    return (float(np.mean(ac)), float(np.mean(bp))) if len(ac) == len(real) and len(bp) == len(cand) else None
test = [s for s in S300 if bys[s].day >= "2026-09-01"]
with cf.ThreadPoolExecutor(10) as ex:
    J = list(ex.map(lambda s: (jrp(RS.get(f"truth|{s}"), RV.get(f"gen|BEST|{s}") or [], f"j|best|{s}"), jrp(RS.get(f"truth|{s}"), CONST, f"j|const|{s}")), test))
json.dump(K, open(cache_f, "w"))
P = np.array([(b[0], b[1], c[0], c[1]) for b, c in J if b and c], float)
def bci(v):
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]; return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1)]
res["themes_vs_constant"] = {"launches": int(len(P)), "constant_list": CONST, "BEST recall": bci(P[:, 0]), "BEST precision": bci(P[:, 1]), "CONST recall": bci(P[:, 2]), "CONST precision": bci(P[:, 3]),
                             "BEST - CONST recall (paired)": bci(P[:, 0] - P[:, 2]), "BEST - CONST precision (paired)": bci(P[:, 1] - P[:, 3])}
res["usd"] = round(USD["usd"], 3)
json.dump(res, open(os.path.join(OUT, "tone_eval.json"), "w"), indent=1, default=str)
print(json.dumps(res["themes_vs_constant"], indent=1), res["usd"])
