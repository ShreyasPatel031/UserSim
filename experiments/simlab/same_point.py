"""Raise SAME-POINT precision / recall and re-score the /try lists under the gemini-2.5-pro adjudicator (orchestrator 10:25Z Nov 12).
Launches: judge_reliability's 96 (60 S300 = PH-description input, BEST lists; 36 fresh = page-read input, site single run); real
themes = its extraction 1. Dev = first 30 S300 + first 18 fresh (by id); confirmation = the rest. Retrieval only from launches dated
strictly before the target (reactions_retrieval bundle, same slug stem excluded).
Lists (dev): BASE (BEST / site run); A specific points only; B1 retrieval + LLM picks which neighbour points recur; B2 retrieval
frequency (no LLM); C two-stage (15 candidates -> rank -> keep 5); D (page only) A from the raw excerpt; RANKED concerns / questions;
controls CONST (generic 6), CAT (most frequent points of the 30 latest earlier same-topic launches), constant / category concern and
question lists. Adjudication: ONE pro call per launch, all items pooled, deduplicated and shuffled (blinded), labels per item and, per
real theme, which items make the SAME POINT, plus GENERIC / SPECIFIC per real theme. Confirmation: BASE + the best dev variant + CONST.
Ceiling: launches with >= 10 comments, comments split in halves; half-B points vs half-A comments under the same adjudicator.
    python same_point.py <ph-website worktree> <scratchpad> <out dir> <phase: dev|confirm|ceiling> [best variant]
"""
import os, sys, json, random
WT, SP0, OUTD, PHASE = sys.argv[1:5]; BESTV = sys.argv[5] if len(sys.argv) > 5 else None; HERE = os.path.dirname(os.path.abspath(__file__))
JR = open(os.path.join(HERE, "judge_reliability.py")).read(); sys.argv = [sys.argv[0], WT, SP0, OUTD]
exec(JR[:JR.index('CF = os.path.join(OUTD, "cache_rel.json")')])
TF = open(os.path.join(HERE, "try_fixes.py")).read().split("\n"); exec("\n".join(TF[145:254]))   # RBE / RBM, emb(), ranked(), cj helpers
REL = json.load(open(os.path.join(SP0, "reliab/cache_rel.json"))); CC = json.load(open(os.path.join(SP0, "stability/cache2.json")))
bys = ns["bys"]; LF = {r.id: r for r in L.itertuples()}
CF = os.path.join(OUTD, f"cache_sp_{PHASE}.json"); C = json.load(open(CF)) if os.path.exists(CF) else {}; csave = lambda: json.dump(C, open(CF, "w"))
USD = {"usd": 0.0}
def info(g, s):
    if g == "S300":
        r = bys[s]; return {"name": r.name, "tagline": r.tagline or "", "text": (r.description or "")[:1500], "raw": None, "day": r.day, "topic": r.topic, "stem": s}
    a = CC[f"gen|{s}"]["read"]; r = LF[s]; tp = (json.loads(r.topics) or ["none"])[0] if isinstance(r.topics, str) and r.topics.startswith("[") else "none"
    return {"name": a["name"], "tagline": a.get("tagline") or "", "text": (a.get("summary") or "")[:1500], "raw": (a.get("page_excerpt") or "")[:2500], "day": r.day, "topic": tp, "stem": r.slug}
SPEC = """A new product is launching on Product Hunt today.
Product: {n} - {t}
{text}
List the 6 most likely SPECIFIC points commenters will raise about THIS product: observations, objections, requests or questions, each
tied to a named feature or claim above. No praise-only lines, no congratulations, no generic questions that fit any product.
Return JSON {{"points": ["...", ...]}}"""
PICK = """A new product is launching on Product Hunt today.
Product: {n} - {t}
{text}
Real commenters on similar earlier launches raised these points:
{pts}
Which of these points (reworded for THIS product) are most likely to come up again here, and why? Pick 6, most likely first.
Return JSON {{"points": ["<the point, reworded for this product>", ...]}}"""
GEN15 = """A new product is launching on Product Hunt today.
Product: {n} - {t}
{text}
Write 15 distinct candidate points real commenters might raise (praise, objections, requests, questions), each specific to this product.
Return JSON {{"points": ["...", ...]}}"""
RANK = """Product: {n} - {t}
{text}
Candidate points commenters might raise:
{c}
Rank them by how likely real Product Hunt commenters are to make exactly that point for THIS product. Return JSON {{"order": [candidate numbers, most likely first]}}"""
CONST_C = ["Pricing is unclear or too high.", "How is this different from existing alternatives?", "Concerns about data privacy and security."]
CONST_Q = ["What does the pricing look like?", "Does it integrate with the tools I already use?", "Is there a free plan or trial?"]
def nbrs(s, inf, k=10):
    q = None
    return q
async def neigh(inf, k=10, topic=False):
    if topic:
        idx = [j for j, m in enumerate(RBM) if m["day"] < inf["day"] and m.get("topic") == inf["topic"] and m["slug_stem"] != inf["stem"]][-30:]
    else:
        qv = (await emb([f"{inf['name']}. {inf['tagline']}. {inf['text'][:800]}"]))[0]; sims = RBE @ qv; idx = []
        for j in np.argsort(-sims):
            if RBM[j]["day"] < inf["day"] and RBM[j]["slug_stem"] != inf["stem"]: idx.append(j)
            if len(idx) == k: break
    return idx
async def freq(idx, n=6, prefix=None):
    th = [(t.split(": ", 1)[-1], j) for j in idx for t in RBM[j]["themes"] if prefix is None or t.lower().startswith(prefix)]
    if not th: return []
    X = await emb([t for t, _ in th]); SS = X @ X.T; own = np.array([j for _, j in th]); used = np.zeros(len(th), bool); out = []
    cnt = np.array([len(set(own[SS[i] >= 0.85])) for i in range(len(th))])
    for i in np.argsort(-cnt):
        if used[i]: continue
        out.append(th[i][0]); used |= SS[i] >= 0.85
        if len(out) == n: break
    return out
async def lists(g, s, full=True):
    key = f"lists|{g}|{s}"
    if key in C and (full <= C[key].get("_full", False)): return C[key]
    inf = info(g, s); T = f"Description: {inf['text']}"; out = {"BASE": [str(x) for x in rows_by[(g, s)][3]][:6], "CONST": CONST}
    mk = lambda tmpl, text, **k: cj(tmpl.format(n=inf["name"], t=inf["tagline"], text=text, **k), tok=1500, temp=0.3)
    out["A"] = [str(x) for x in ((await mk(SPEC, T)).get("points") or [])][:6]
    if inf["raw"]: out["D"] = [str(x) for x in ((await mk(SPEC, "Page text: " + inf["raw"])).get("points") or [])][:6]
    if full:
        nb = await neigh(inf); pts = [t.split(": ", 1)[-1] for j in nb for t in RBM[j]["themes"]][:80]
        out["B1"] = [str(x) for x in ((await mk(PICK, T, pts="\n".join(f"- {p}" for p in pts))).get("points") or [])][:6]
        out["B2"] = await freq(nb)
        c15 = [str(x) for x in ((await mk(GEN15, T)).get("points") or [])][:15]
        o = (await cj(RANK.format(n=inf["name"], t=inf["tagline"], text=T, c="\n".join(f"{i+1}. {p}" for i, p in enumerate(c15))), tok=400)).get("order") or []
        out["C"] = [c15[int(i) - 1] for i in o if str(i).isdigit() and 0 < int(i) <= len(c15)][:5]
        tn = await neigh(inf, topic=True); out["CAT"] = await freq(tn)
        d = inf["text"] if g == "S300" else inf["text"] + " " + (inf["raw"] or "")[:1500]
        out["RC"] = (await ranked(inf["name"], inf["tagline"], d, "concerns", inf["day"]))[0][:5]
        out["RQ"] = (await ranked(inf["name"], inf["tagline"], d, "questions", inf["day"]))[0][:5]
        out["RC_CONST"], out["RQ_CONST"] = CONST_C, CONST_Q
        out["RC_CAT"] = await freq(tn, 3, "objection"); out["RQ_CAT"] = await freq(tn, 3, "question")
    out["_full"] = full; C[key] = out; csave(); return out
ADJ = """You are adjudicating whether simulated points about a product launch match what REAL users said. Rubric:
SAME_POINT = a reader would say the item makes the same specific observation, complaint, request or question as at least one real comment.
SAME_TOPIC = same feature area or the same generic sentiment, but a different specific point.  UNRELATED = neither.
REAL COMMENTS:
{comments}

REAL THEMES (summary of the comments):
{themes}

SIMULATED ITEMS:
{items}

Return JSON {{"items": ["SAME_POINT"|"SAME_TOPIC"|"UNRELATED" per simulated item],
"themes": [{{"same_point_items": [numbers of simulated items that make the SAME specific point as this theme], "kind": "GENERIC"|"SPECIFIC"}} per real theme]}}
(GENERIC = congratulations, generic praise, or a question that would fit almost any product; SPECIFIC = tied to this product.)"""
LV = {"SAME_POINT": 2, "SAME_TOPIC": 1, "UNRELATED": 0}
async def adjudicate(key, comments, themes, L_):
    if key in C: return C[key]
    if USD["usd"] > 2.8: return None
    pool = list(dict.fromkeys(t for v in L_.values() for t in v)); random.Random(key).shuffle(pool)
    p = ADJ.format(comments="\n".join(f"- {str(t)[:300]}" for t in list(comments)[:40]), themes="\n".join(f"{i+1}. {t}" for i, t in enumerate(themes)),
                   items="\n".join(f"{i+1}. {t}" for i, t in enumerate(pool)))
    try:
        raw = await GC.gemini_chat([{"role": "user", "content": p}], model="gemini-2.5-pro", temperature=0.0, thinking_budget=128, max_retries=3, max_output_tokens=4000)
        a = GC.extract_json(raw) or {}
    except Exception as e: a = {}
    USD["usd"] += len(p) / 4 * 1.25e-6 + (128 + 12 * len(pool) + 25 * len(themes)) * 10e-6
    it, th = a.get("items") or [], a.get("themes") or []
    if len(it) != len(pool) or len(th) != len(themes): C[key] = None; csave(); return None
    lab = {t: LV.get(str(x).upper(), 0) for t, x in zip(pool, it)}; pos = {t: i + 1 for i, t in enumerate(pool)}
    out = {}
    for name, v in L_.items():
        out[name] = {"labels": [lab[t] for t in v], "covers": [any(pos[t] in (x.get("same_point_items") or []) for t in v) if isinstance(x, dict) else False for x in th]}
    out["_kind"] = [str((x or {}).get("kind", "")).upper() if isinstance(x, dict) else "" for x in th]
    C[key] = out; csave(); return out
rows_by = {(r[0], r[1]): r for r in rows}
ids = {g: sorted(s for gg, s in rows_by if gg == g) for g in ("S300", "FRESH")}
DEV = [("S300", s) for s in ids["S300"][:30]] + [("FRESH", s) for s in ids["FRESH"][:18]]
CONF = [("S300", s) for s in ids["S300"][30:]] + [("FRESH", s) for s in ids["FRESH"][18:]]

async def run_set(S, full, keep=None):
    sem = asyncio.Semaphore(5)
    async def one(g, s):
        async with sem:
            rel = REL.get(f"{g}|{s}")
            if not rel or not rel["ex"][0]["themes"]: return None
            Ls = await lists(g, s, full); Ls = {k: v for k, v in Ls.items() if not k.startswith("_") and v and (keep is None or k in keep)}
            return (g, s, await adjudicate(f"adj|{PHASE}|{g}|{s}", rows_by[(g, s)][2], rel["ex"][0]["themes"], Ls))
    return [x for x in await asyncio.gather(*[one(g, s) for g, s in S]) if x and x[2]]
def mb(v):
    v = np.array([x for x in v if x is not None and not np.isnan(x)], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
def metrics(R, name, k=None):
    pre = lambda o: np.mean([x == 2 for x in o[name]["labels"][:k]]) if name in o and o[name]["labels"] else np.nan
    rec = lambda o: np.mean(o[name]["covers"]) if name in o and o[name]["covers"] else np.nan
    rec_s = lambda o: (np.mean([c for c, kd in zip(o[name]["covers"], o["_kind"]) if kd == "SPECIFIC"]) if name in o and any(kd == "SPECIFIC" for kd in o["_kind"]) else np.nan)
    hit = lambda o: float(any(x == 2 for x in o[name]["labels"][:k])) if name in o and o[name]["labels"] else np.nan
    return {"precision" if k is None else f"p@{k}": [pre(o) for _, _, o in R], "recall": [rec(o) for _, _, o in R], "recall_specific": [rec_s(o) for _, _, o in R], "hit": [hit(o) for _, _, o in R]}
def summarize(R, names, base="BASE"):
    out = {}
    for G in ("S300", "FRESH"):
        RG = [r for r in R if r[0] == G]; o = {"launches": len(RG)}
        for n_ in names:
            k = 3 if n_.startswith("R") else None; m = metrics(RG, n_, k); o[n_] = {kk: mb(v) for kk, v in m.items() if kk != "hit" or k}
            if n_ != base and not n_.startswith("R") and base in names:
                mbm = metrics(RG, base)
                o[n_ + " - " + base] = {kk: mb(np.array(m[kk]) - np.array(mbm[kk])) for kk in ("precision", "recall")}
        kinds = [kd for _, _, x in RG for kd in x["_kind"]]; o["real_theme_kinds"] = {"GENERIC": kinds.count("GENERIC"), "SPECIFIC": kinds.count("SPECIFIC")}
        out[G] = o
    return out
if PHASE == "dev":
    R = asyncio.run(run_set(DEV, True)); names = ["BASE", "A", "B1", "B2", "C", "D", "CONST", "CAT", "RC", "RC_CONST", "RC_CAT", "RQ", "RQ_CONST", "RQ_CAT"]
    res = {"phase": "dev", "est_usd": round(USD["usd"], 2), **summarize(R, names)}
elif PHASE == "confirm":
    R = asyncio.run(run_set(CONF, False, keep={"BASE", "CONST", BESTV} | ({"A"} if BESTV == "D" else set())))
    res = {"phase": "confirm", "variant": BESTV, "est_usd": round(USD["usd"], 2), **summarize(R, ["BASE", BESTV, "CONST"])}
else:   # ceiling: real-vs-real split halves
    async def ceil_one(g, s, sem):
        async with sem:
            key = f"ceil|{g}|{s}"
            if key in C: return C[key]
            cm = list(rows_by[(g, s)][2])
            if len(cm) < 10: return None
            random.Random(s).shuffle(cm); A_, B_ = cm[::2], cm[1::2]
            ex = lambda c: cj(TRUTH.format(c="\n".join(f"- {str(t)[:400]}" for t in c[:40])), tok=2000)
            ta = [str(t.get("theme")) for t in ((await ex(A_)).get("themes") or []) if isinstance(t, dict) and t.get("theme")][:8]
            tb_ = [str(t.get("theme")) for t in ((await ex(B_)).get("themes") or []) if isinstance(t, dict) and t.get("theme")][:6]
            o = await adjudicate(f"adjceil|{g}|{s}", A_, ta, {"HALF_B": tb_}) if ta and tb_ else None
            C[key] = o; csave(); return o
    async def ceil_all():
        sem = asyncio.Semaphore(5); S = [("S300", s) for s in ids["S300"]]; outs = await asyncio.gather(*[ceil_one(g, s, sem) for g, s in S])
        return [(g, s, o) for (g, s), o in zip(S, outs) if o]
    R = asyncio.run(ceil_all()); m = metrics(R, "HALF_B")
    kinds = [kd for _, _, x in R for kd in x["_kind"]]
    res = {"phase": "ceiling", "est_usd": round(USD["usd"], 2), "launches": len(R), "half_B_vs_half_A": {k: mb(v) for k, v in m.items() if k != "hit"},
           "real_theme_kinds": {"GENERIC": kinds.count("GENERIC"), "SPECIFIC": kinds.count("SPECIFIC")}}
json.dump(res, open(os.path.join(OUTD, f"same_point_{PHASE}.json"), "w"), indent=1, default=float); print(json.dumps(res, default=float))
