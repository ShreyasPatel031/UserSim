"""Retrieval instead of generation for concerns / questions (orchestrator 02:09Z Nov 13). Same 70 launches as page_path.py, two input modes
(ph = real PH description, page = raw page excerpt, the deployed page-path input). Neighbours: past launches in the reactions_retrieval bundle
(themes extracted from their REAL comments), dated strictly before the target day, same slug stem excluded, by gemini-embedding cosine.
  a5   verbatim: the top real point (by bundle order) of each of the 5 nearest, nearest first (concern = objection / question / feature request)
  a5t  same, nearest within the same topic
  b20  gemini-2.5-flash condenses the 20 nearest launches' real points into a ranked top-3 for the target
  c    current deployed generation: try_fixes.ranked() (from page_path's cache, same lists as reported there)
  d    generic constant list
Adjudicator: gemini-2.5-pro, temperature 0, sees the real comments; one call per launch per kind (concerns / questions), both modes'
items pooled, shuffled, blinded; it labels each item SAME_POINT / not and maps each of the launch's real points (flash extraction of the
real comments, top 3) to matching items -> precision p@3, recall (share of real points matched by any of the arm's 3), top-1 hit.
    python retrieval_react.py <ph-website worktree> <scratchpad> <page_path out dir> <out dir>
"""
import os, sys, json, random, time
WT, SP0, PPD, OUT = sys.argv[1:5]; OUT_RR = OUT; HERE = os.path.dirname(os.path.abspath(__file__))
PP = open(os.path.join(HERE, "page_path.py")).read(); sys.argv = [sys.argv[0], WT, SP0, PPD]
exec(PP[:PP.index("async def one(x, sem):")])
PPC = json.load(open(os.path.join(PPD, "cache_pp.json"))); os.makedirs(OUT, exist_ok=True)
OUT = OUT_RR; CF = os.path.join(OUT, "cache_rr.json"); C = json.load(open(CF)) if os.path.exists(CF) else {}; csave = lambda: json.dump(C, open(CF, "w"))
USD = {"usd": 0.0, "gen": 0.0}
PRE = {"RC": ("objection", "question", "feature request", "feature_request"), "RQ": ("question",)}
def pts(j, pre): return [t.split(":", 1)[1].strip() for t in RBM[j]["themes"] if t.split(":", 1)[0].strip().lower() in PRE[pre]]
async def nearest(n, t, d, day, stem, topic, k):
    q = (await emb([f"{n}. {t}. {d[:800]}"]))[0]; out = []
    for j in np.argsort(-(RBE @ q)):
        m = RBM[j]
        if m["day"] < day and m["slug_stem"] != stem and (topic is None or m.get("topic") == topic): out.append(int(j))
        if len(out) == k: break
    return out
def verb(nb, pre):
    out = []
    for r in range(3):
        for j in nb:
            p = pts(j, pre)
            if len(p) > r and p[r] not in out: out.append(p[r])
            if len(out) == 3: return out
    return out
COND = """A new product is launching on Product Hunt today.
Product: {n} - {t}
{d}
Real users raised these points in the launch comments of the 20 most similar EARLIER launches (one line per point, launch number first):
{p}
Using these real points as evidence of what this audience asks about, write the 3 {what} most likely to be raised about THIS product,
most likely first, each reworded for this product. Return JSON {{"items": ["...", "...", "..."]}}"""
async def cond(n, t, d, nb, pre):
    p = "\n".join(f"[{i+1}] {x}" for i, j in enumerate(nb) for x in pts(j, pre)[:4])
    if not p: return []
    pr = COND.format(n=n, t=t, d=d[:1500], p=p[:6000], what="concerns, objections or feature requests" if pre == "RC" else "questions to the makers")
    USD["gen"] += len(pr) / 4 * 0.3e-6 + 200 * 2.5e-6
    return [str(x) for x in ((await cj(pr, tok=600)).get("items") or [])][:3]
ADJ2 = """You are adjudicating whether predicted {what} match what REAL users said in a product's launch comments.
SAME_POINT = a reader would say the item raises the same specific {one} as at least one real comment. Otherwise NOT.
REAL COMMENTS:
{comments}

REAL POINTS (numbered R1..):
{real}

PREDICTED ITEMS (numbered 1..):
{items}

Return JSON {{"items": ["SAME_POINT"|"NOT" per predicted item], "real": [[numbers of the predicted items that make the same point as R1], ...one list per real point]}}"""
async def adj(key, comments, real, lists, pre):
    if key in C: return C[key]
    if USD["usd"] > 3.0: return None
    pool = list(dict.fromkeys(x for v in lists.values() for x in v)); random.Random(key).shuffle(pool)
    p = ADJ2.format(what="concerns" if pre == "RC" else "questions", one="concern, objection or request" if pre == "RC" else "question",
                    comments="\n".join(f"- {str(x)[:300]}" for x in list(comments)[:40]), real="\n".join(f"R{i+1}. {x}" for i, x in enumerate(real)),
                    items="\n".join(f"{i+1}. {x}" for i, x in enumerate(pool)))
    try: a = GC.extract_json(await GC.gemini_chat([{"role": "user", "content": p}], model="gemini-2.5-pro", temperature=0.0, thinking_budget=128, max_retries=3, max_output_tokens=3000)) or {}
    except Exception: a = {}
    USD["usd"] += len(p) / 4 * 1.25e-6 + (128 + 12 * len(pool)) * 10e-6
    it, rr = a.get("items") or [], a.get("real") or []
    if len(it) != len(pool) or len(rr) != len(real): C[key] = None; csave(); return None
    lab = {x: str(y).upper() == "SAME_POINT" for x, y in zip(pool, it)}; idx = {x: i + 1 for i, x in enumerate(pool)}
    sets = [set(int(z) for z in (r if isinstance(r, list) else []) if str(z).isdigit()) for r in rr]
    out = {nm: {"lab": [lab[x] for x in v], "rec": float(np.mean([bool(s & {idx[x] for x in v}) for s in sets])) if sets else None} for nm, v in lists.items()}
    C[key] = out; csave(); return out
async def one(x, sem):
    async with sem:
        k = f"lists|{x['key']}"
        if k not in C:
            rd = x["read"]; pc = PPC.get(f"lists|{x['key']}", {})
            modes = {"ph": x["ph"], "page": (rd.get("name") or x["ph"][0], rd.get("tagline") or "", rd.get("page_excerpt") or "")}
            out = {}
            for mo, (n, t, d) in modes.items():
                if not d.strip(): continue
                nb = await nearest(n, t, d, x["day"], x["stem"], None, 20); nbt = await nearest(n, t, d, x["day"], x["stem"], x["topic"], 5)
                for pre in ("RC", "RQ"):
                    out[f"{pre}|{mo}|a5"] = verb(nb[:5], pre); out[f"{pre}|{mo}|a5t"] = verb(nbt, pre); out[f"{pre}|{mo}|b20"] = await cond(n, t, d, nb, pre)
                    out[f"{pre}|{mo}|c"] = (pc.get(f"{pre}_{'c_ph' if mo == 'ph' else 'b_raw'}") or [])[:3]
                    out[f"{pre}|{mo}|d"] = (CONST_C if pre == "RC" else CONST_Q)[:3]
            T = await cj(EX.format(c="\n".join(f"- {str(z)[:400]}" for z in list(x["comments"])[:40])), tok=1500)
            out["real|RC"] = [str(z) for z in (T.get("critical") or [])][:3]; out["real|RQ"] = [str(z) for z in (T.get("questions") or [])][:3]
            C[k] = out; csave()
        L_ = C[k]; res = {}
        for pre in ("RC", "RQ"):
            ls = {kk.split("|", 1)[1]: v for kk, v in L_.items() if kk.startswith(pre + "|") and v}
            res[pre] = await adj(f"adj|{pre}|{x['key']}", x["comments"], L_[f"real|{pre}"], ls, pre) if L_[f"real|{pre}"] else None
        return x, res
async def main():
    sem = asyncio.Semaphore(5); return await asyncio.gather(*[one(x, sem) for x in LAUNCH])
t0 = time.time(); R = asyncio.run(main())
def mb(v):
    v = np.array([z for z in v if z is not None and not np.isnan(z)], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
met = {"p@3": lambda o: float(np.mean(o["lab"][:3])), "recall": lambda o: o["rec"] if o["rec"] is not None else np.nan, "top1": lambda o: float(o["lab"][0])}
g = lambda o, nm, m: met[m](o[nm]) if o and o.get(nm) and o[nm]["lab"] else np.nan
out = {"design": __doc__.split("\n    python")[0], "launches": len(LAUNCH), "est_usd_adjudicator": round(USD["usd"], 2), "est_usd_generation_b20_total": round(USD["gen"], 3)}
for pre, kind in (("RC", "concerns"), ("RQ", "questions")):
    for mo in ("ph", "page"):
        o_ = {}
        for m in ("p@3", "recall", "top1"):
            o_[m] = {arm: mb([g(r[pre], f"{mo}|{arm}", m) for _, r in R]) for arm in ("a5", "a5t", "b20", "c", "d")}
            for arm in ("a5", "a5t", "b20"):
                for ctl in ("c", "d"): o_[m][f"{arm} - {ctl}"] = mb([g(r[pre], f"{mo}|{arm}", m) - g(r[pre], f"{mo}|{ctl}", m) for _, r in R])
            o_[m]["c - d"] = mb([g(r[pre], f"{mo}|c", m) - g(r[pre], f"{mo}|d", m) for _, r in R])
        out[f"{kind}|{mo}"] = o_
json.dump(out, open(os.path.join(OUT, "retrieval_react.json"), "w"), indent=1, default=float)
print(json.dumps({k: v for k, v in out.items() if k != "design"}, default=float)[:200], round(time.time() - t0))
