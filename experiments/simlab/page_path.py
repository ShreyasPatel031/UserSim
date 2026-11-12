"""Page-read path under the SAME-POINT standard (orchestrator 12:44Z Nov 12). Ranked concerns / questions (try_fixes.ranked, retrieval
strictly before the launch day) from three inputs on the same launches: (a) the page read summary (name, tagline, summary), (b) the raw
page excerpt, (c) the pasted PH description; controls = constant list and category points (same-topic earlier launches). One
gemini-2.5-pro call per launch (temperature 0, sees the real comments), all top-3 items pooled + shuffled; p@3 / hit@3, paired bootstrap.
Launches: fresh page reads (Oct 27 - Nov 10, fetched ~1-15 days after launch) with >= 5 non-team comments, topped up with held Sep-Oct page
reads of S300 launches (fetched Oct 25, flagged late). Ceiling: launches with >= 10 comments, comments split in halves, the top-3
critical points / questions of half B (try_fixes EX) adjudicated against half A.
    python page_path.py <ph-website worktree> <scratchpad> <out dir>
"""
import os, sys, json, random
WT, SP0, OUTD = sys.argv[1:4]; HERE = os.path.dirname(os.path.abspath(__file__))
SPS = open(os.path.join(HERE, "same_point.py")).read(); sys.argv = [sys.argv[0], WT, SP0, OUTD, "pagepath"]
exec(SPS[:SPS.index('ADJ = """You are adjudicating')])   # rows, truth_c, ranked(), neigh(), freq(), CONST_C / CONST_Q, cj, GC, L, K, bys
os.makedirs(OUTD, exist_ok=True); CF = os.path.join(OUTD, "cache_pp.json"); C = json.load(open(CF)) if os.path.exists(CF) else {}; csave = lambda: json.dump(C, open(CF, "w"))
BP = json.load(open(os.path.join(SP0, "band_page/cache.json"))); USD = {"usd": 0.0}
tpk = lambda s: (json.loads(s) or ["none"])[0] if isinstance(s, str) and s.startswith("[") else "none"
LAUNCH = []
for r in L.itertuples():   # fresh
    rd = (K.get(f"p|{r.id}") or {}).get("read")
    if rd and len(truth_c.get(r.id, [])) >= 5:
        LAUNCH.append({"key": f"F|{r.id}", "fetch": "fresh", "comments": truth_c[r.id], "read": rd, "ph": (r.name, r.tagline or "", r.description or ""), "day": r.day, "topic": tpk(r.topics), "stem": r.slug})
idmap = {str(r.id): s for s, r in bys.items()}
for i, v in BP.items():   # held Sep-Oct page reads of S300 launches
    s = idmap.get(str(i))
    if len(LAUNCH) >= 70: break
    if s and "fail" not in v and s in ns["com"] and len(ns["com"][s]) >= 5 and "2026-09-01" <= bys[s].day <= "2026-10-24":
        r = bys[s]; LAUNCH.append({"key": f"H|{s}", "fetch": "late (Oct 25)", "comments": list(ns["com"][s].values()), "read": v, "ph": (r.name, r.tagline or "", r.description or ""), "day": r.day, "topic": r.topic, "stem": s})
print("launches", len(LAUNCH), {f: sum(x["fetch"] == f for x in LAUNCH) for f in ("fresh", "late (Oct 25)")}, flush=True)
ADJ = """You are adjudicating whether predicted concerns / questions match what REAL users said in a product's launch comments.
SAME_POINT = a reader would say the item raises the same specific concern, request or question as at least one real comment.
SAME_TOPIC = same area, different point.  UNRELATED = neither.
REAL COMMENTS:
{comments}

PREDICTED ITEMS:
{items}

Return JSON {{"items": ["SAME_POINT"|"SAME_TOPIC"|"UNRELATED" per item]}}"""
async def adjudicate(key, comments, lists):
    if key in C: return C[key]
    if USD["usd"] > 1.0: return None
    pool = list(dict.fromkeys(t for v in lists.values() for t in v)); random.Random(key).shuffle(pool)
    p = ADJ.format(comments="\n".join(f"- {str(t)[:300]}" for t in list(comments)[:40]), items="\n".join(f"{i+1}. {t}" for i, t in enumerate(pool)))
    try: a = GC.extract_json(await GC.gemini_chat([{"role": "user", "content": p}], model="gemini-2.5-pro", temperature=0.0, thinking_budget=128, max_retries=3, max_output_tokens=2000)) or {}
    except Exception: a = {}
    USD["usd"] += len(p) / 4 * 1.25e-6 + (128 + 10 * len(pool)) * 10e-6
    it = a.get("items") or []
    if len(it) != len(pool): C[key] = None; csave(); return None
    lab = {t: str(x).upper() == "SAME_POINT" for t, x in zip(pool, it)}
    out = {n: [lab[t] for t in v] for n, v in lists.items()}; C[key] = out; csave(); return out
async def one(x, sem):
    async with sem:
        k = f"lists|{x['key']}"
        if k not in C:
            rd = x["read"]; n_, t_ = rd.get("name") or x["ph"][0], rd.get("tagline") or ""
            inputs = {"a_read": (n_, t_, rd.get("summary") or ""), "b_raw": (n_, t_, rd.get("page_excerpt") or ""), "c_ph": x["ph"]}
            L_ = {}
            for nm, (n, t, d) in inputs.items():
                if not d.strip(): continue
                L_[f"RC_{nm}"] = (await ranked(n, t, d, "concerns", x["day"]))[0][:3]; L_[f"RQ_{nm}"] = (await ranked(n, t, d, "questions", x["day"]))[0][:3]
            inf = {"name": n_, "tagline": t_, "text": rd.get("summary") or "", "day": x["day"], "topic": x["topic"], "stem": x["stem"]}
            tn = await neigh(inf, topic=True); L_["RC_cat"] = await freq(tn, 3, "objection"); L_["RQ_cat"] = await freq(tn, 3, "question")
            L_["RC_const"], L_["RQ_const"] = CONST_C, CONST_Q; C[k] = L_; csave()
        L_ = {n: v for n, v in C[k].items() if v}
        return x, await adjudicate(f"adj|{x['key']}", x["comments"], L_)
async def main():
    sem = asyncio.Semaphore(5); return await asyncio.gather(*[one(x, sem) for x in LAUNCH])
R = [(x, o) for x, o in asyncio.run(main()) if o]
def mb(v):
    v = np.array([z for z in v if z is not None and not np.isnan(z)], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
p3 = lambda o, n: float(np.mean(o[n][:3])) if o.get(n) else np.nan
h3 = lambda o, n: float(any(o[n][:3])) if o.get(n) else np.nan
res = {"design": __doc__.split("\n    python")[0], "est_usd_adjudicator": round(USD["usd"], 2), "launches": len(R),
       "by_fetch": {f: sum(x["fetch"] == f for x, _ in R) for f in ("fresh", "late (Oct 25)")}}
for kind in ("RC", "RQ"):
    o_ = {}
    for arm in ("a_read", "b_raw", "c_ph", "cat", "const"):
        n = f"{kind}_{arm}"; o_[arm] = {"p@3": mb([p3(o, n) for _, o in R]), "hit@3": mb([h3(o, n) for _, o in R])}
    for arm in ("a_read", "b_raw", "c_ph"):
        for ctl in ("const", "cat"):
            o_[f"{arm} - {ctl} (p@3, paired)"] = mb([p3(o, f"{kind}_{arm}") - p3(o, f"{kind}_{ctl}") for _, o in R])
    o_["b_raw - a_read (p@3, paired)"] = mb([p3(o, f"{kind}_b_raw") - p3(o, f"{kind}_a_read") for _, o in R])
    o_["fresh only a_read / b_raw / c_ph / const p@3"] = [mb([p3(o, f"{kind}_{a}") for x, o in R if x["fetch"] == "fresh"])[0] if R else None for a in ("a_read", "b_raw", "c_ph", "const")]
    res["concerns" if kind == "RC" else "questions"] = o_
# ceiling: real critical points / questions, split-half
async def ceil(x, sem):
    async with sem:
        k = f"ceil|{x['key']}"
        if k in C: return C[k]
        cm = list(x["comments"])
        if len(cm) < 10: return None
        random.Random(x["key"]).shuffle(cm); A_, B_ = cm[::2], cm[1::2]
        T = await cj(EX.format(c="\n".join(f"- {str(t)[:400]}" for t in B_[:40])), tok=1500)
        o = await adjudicate(f"adjceil|{x['key']}", A_, {"RC_half": [str(z) for z in (T.get("critical") or [])][:3], "RQ_half": [str(z) for z in (T.get("questions") or [])][:3]})
        C[k] = o; csave(); return o
async def ceil_all():
    sem = asyncio.Semaphore(5); return await asyncio.gather(*[ceil(x, sem) for x in LAUNCH])
CE = [o for o in asyncio.run(ceil_all()) if o]
res["ceiling_real_vs_real"] = {"launches": len(CE), "concerns p@3": mb([p3(o, "RC_half") for o in CE]), "questions p@3": mb([p3(o, "RQ_half") for o in CE]),
                               "concerns hit@3": mb([h3(o, "RC_half") for o in CE]), "questions hit@3": mb([h3(o, "RQ_half") for o in CE])}
res["est_usd_adjudicator"] = round(USD["usd"], 2)
json.dump(res, open(os.path.join(OUTD, "page_path.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
