"""Extend b20 (orchestrator 02:39Z Nov 13). Launch set = the pooled 170 of retrieval_rep.py (first 70 + new 100), both input paths.
Neighbour exclusions (all new lists, recipe RECIPE_b20_concerns.md): day < target day, slug stem after dropping "-N" differs, neither stem
contains the other. Strict gemini-2.5-pro judge (temperature 0, sees real comments), one call per launch per part, items pooled + blinded.
 (1) bank: v1 (3,371 launches, >= 5 comments, Jan 1 - Oct 24) vs v2 (bank_v2.py: >= 3 comments + Oct 27 - Nov 10 API pulls).
     Thin share = targets whose top-1 cosine is below the recipe thresholds (PH 0.898 / page 0.886). Concerns: b20 on v1 (the cached
     replication lists) vs b20 on v2 vs deployed vs constant.
 (2) reactions (what users say, incl. praise): b20-R (20 nearest v1 launches, up to 4 themes each of any type, flash writes the 6 most
     likely comments) vs deployed step_reactions (site code; first 70 from page_react2's cache) vs a constant 6.
 (3) sweep on a held-out half (dev = sha1(key) even): k = 10/20/40 x points 2/4/8, concerns, bank v1, points cap 16k chars;
     the dev winner (mean p@3 over both paths) is confirmed on the other half vs recipe b20 (k20 p4), deployed and constant.
Metrics: p@3 (reactions: precision over all 6, and p@3), recall of the launch's real top points, top-1; paired launch bootstrap.
    python b20_ext.py <ph-website worktree> <scratchpad> <page_path out dir> <rr dir (cache)> <bank_v2 dir> <out dir>
"""
import os, sys, json, random, re, hashlib
os.environ["TRY_GLOBAL_DAY"] = "100000"; os.environ["TRY_PER_IP_DAY"] = "100000"; os.environ["TRY_PER_IP_HOUR"] = "100000"
HERE = os.path.dirname(os.path.abspath(__file__)); BK, OUTX = sys.argv[5], sys.argv[6]
RP = open(os.path.join(HERE, "retrieval_rep.py")).read(); sys.argv = sys.argv[:5]; exec(RP[:RP.index("async def one(x, sem, seed2=False):")])
os.makedirs(OUTX, exist_ok=True)
E2 = np.load(os.path.join(BK, "bank_v2_emb.npy")); M2 = json.load(open(os.path.join(BK, "bank_v2.json")))
BANKS = {"v1": (RBE, RBM), "v2": (E2, M2)}; THR = {"ph": 0.898, "page": 0.886}
PREX = {"RC": ("objection", "question", "feature request", "feature_request"), "RQ": ("question",), "RX": None}
def ptsb(M, j, pre):
    out = []
    for t in M[j]["themes"]:
        h, _, b = t.partition(":")
        if b and (PREX[pre] is None or h.strip().lower() in PREX[pre]): out.append(b.strip())
    return out
QC = {}
async def qv(n, t, d):
    s = f"{n}. {t}. {d[:800]}"
    if s not in QC: QC[s] = (await emb([s]))[0]
    return QC[s]
def near(bank, q, day, stem, k):
    E_, M_ = BANKS[bank]; s = E_ @ q; o = []; ts = st(stem)
    for j in np.argsort(-s):
        m = M_[j]; ms = st(m["slug_stem"])
        if m["day"] >= day or ms == ts or (len(ts) >= 4 and len(ms) >= 4 and (ts in ms or ms in ts)): continue
        o.append((int(j), float(s[j])))
        if len(o) == k: break
    return o
WHAT = {"RC": "concerns, objections or feature requests", "RQ": "questions to the makers"}
CONDR = """A new product is launching on Product Hunt today.
Product: {n} - {t}
{d}
Real users raised these points in the launch comments of the 20 most similar EARLIER launches (one line per point, launch number first):
{p}
Using these real points as evidence of what this audience says, write the 6 comments real users are most likely to post about THIS
product (any kind: praise, questions, objections, requests, comparisons), most likely first, each reworded for this product as a short
launch-day comment. Return JSON {{"items": ["...", ...]}}"""
async def condb(n, t, d, bank, nb, pre, npts, cap=6000):
    M_ = BANKS[bank][1]; p = "\n".join(f"[{i+1}] {x}" for i, (j, _) in enumerate(nb) for x in ptsb(M_, j, pre)[:npts])
    if not p: return []
    if pre == "RX": pr = CONDR.format(n=n, t=t, d=d[:1500], p=p[:cap]); nn = 6
    else: pr = COND.format(n=n, t=t, d=d[:1500], p=p[:cap], what=WHAT[pre]); nn = 3
    USD["gen"] += len(pr) / 4 * 0.3e-6 + 300 * 2.5e-6
    return [str(x) for x in ((await cj(pr, tok=900)).get("items") or [])][:nn]
ADJX = """You are adjudicating whether predicted {what} match what REAL users said in a product's launch comments.
SAME_POINT = a reader would say the item makes the same specific point ({one}) as at least one real comment. Otherwise NOT.
REAL COMMENTS:
{comments}

REAL POINTS (numbered R1..):
{real}

PREDICTED ITEMS (numbered 1..):
{items}

Return JSON {{"items": ["SAME_POINT"|"NOT" per predicted item], "real": [[numbers of the predicted items that make the same point as R1], ...one list per real point]}}"""
WD = {"RC": ("concerns", "concern, objection or request"), "RQ": ("questions", "question"), "RX": ("launch comments", "praise, question, objection, request or comparison")}
async def adjx(key, comments, real, lists, pre):
    if key in C: return C[key]
    if USD["usd"] > float(os.environ.get("ADJ_CAP", "8")): return None
    pool = list(dict.fromkeys(x for v in lists.values() for x in v)); random.Random(key).shuffle(pool)
    p = ADJX.format(what=WD[pre][0], one=WD[pre][1], comments="\n".join(f"- {str(x)[:300]}" for x in list(comments)[:40]),
                    real="\n".join(f"R{i+1}. {x}" for i, x in enumerate(real)), items="\n".join(f"{i+1}. {str(x)[:400]}" for i, x in enumerate(pool)))
    try: a = GC.extract_json(await GC.gemini_chat([{"role": "user", "content": p}], model="gemini-2.5-pro", temperature=0.0, thinking_budget=128, max_retries=3, max_output_tokens=6000)) or {}
    except Exception: a = {}
    USD["usd"] += len(p) / 4 * 1.25e-6 + (128 + 12 * len(pool)) * 10e-6
    it, rr = a.get("items") or [], a.get("real") or []
    if len(it) != len(pool) or len(rr) != len(real): C[key] = None; csave(); return None
    lab = {x: str(y).upper() == "SAME_POINT" for x, y in zip(pool, it)}; idx = {x: i + 1 for i, x in enumerate(pool)}
    sets = [set(int(z) for z in (r if isinstance(r, list) else []) if str(z).isdigit()) for r in rr]
    out = {nm: {"lab": [lab[x] for x in v], "rec": float(np.mean([bool(s & {idx[x] for x in v}) for s in sets])) if sets else None} for nm, v in lists.items()}
    C[key] = out; csave(); return out
PPCR = json.load(open(os.path.join(PPD, "cache_pp.json")))
CONSTR = ["Congrats on the launch!", "How is this different from existing alternatives?", "What does the pricing look like?",
          "Does it integrate with the tools I already use?", "The interface looks clean and easy to use.", "Is there a free plan or trial?"]
rt = lambda rx: [f"{x.get('comment', '')}" for x in (rx or {}).get("reactions", [])][:6]
async def react(a):
    try: return rt(await try_sim.step_reactions(try_sim.new_run(a)))
    except Exception: return []
RXT = """Below are real user comments on a product launch (makers' own comments removed). List the 6 most common distinct points users made
(any kind: praise, questions, objections, requests, comparisons), most frequent first, one short sentence each.
Return JSON {{"points": ["...", ...]}}
Comments:
{c}"""
dev = lambda x: int(hashlib.sha1(x["key"].encode()).hexdigest(), 16) % 2 == 0
SWEEP = [(k, p) for k in (10, 20, 40) for p in (2, 4, 8)]
def modes(x):
    rd = x["read"]; return {"ph": x["ph"], "page": (rd.get("name") or x["ph"][0], rd.get("tagline") or "", rd.get("page_excerpt") or "")}
async def one(x, sem):
    async with sem:
        base = C[f"lists|{x['key']}"]; md = {m: v for m, v in modes(x).items() if v[2].strip()}; k = f"ext|{x['key']}"
        if k not in C:
            o = {"sim1": {}}
            for mo, (n, t, d) in md.items():
                q = await qv(n, t, d)
                for b in ("v1", "v2"):
                    nb = near(b, q, x["day"], x["stem"], 40); o["sim1"][f"{b}|{mo}"] = nb[0][1] if nb else None
                o[f"RC|{mo}|b20v2"] = await condb(n, t, d, "v2", near("v2", q, x["day"], x["stem"], 20), "RC", 4)
                o[f"RX|{mo}|b20"] = await condb(n, t, d, "v1", near("v1", q, x["day"], x["stem"], 20), "RX", 4)
            rc = PPCR.get(f"react2|{x['key']}") or {}
            for mo, (n, t, d) in md.items():
                dep = [str(z).rsplit(" (", 1)[0] for z in (rc.get(mo) or [])][:6]
                if not dep:
                    rd = x["read"]; tops = rd.get("topics") or ["Productivity"]; b0 = {"audience": "", "pricing": "unknown", "strengths": [], "doubts": [], "clarity": None, "url": ""}
                    if mo == "page": dep = await react({**b0, **{kk: rd.get(kk) for kk in ("name", "tagline", "summary", "topics", "audience", "pricing", "strengths", "doubts", "page_excerpt")}})
                    else: dep = await react({**b0, "name": n, "tagline": t, "summary": d[:400], "topics": tops, "page_excerpt": d[:2500], "ph_description": d})
                o[f"RX|{mo}|dep"] = dep; o[f"RX|{mo}|const"] = CONSTR
            T = await cj(RXT.format(c="\n".join(f"- {str(z)[:400]}" for z in list(x["comments"])[:40])), tok=1200); o["real|RX"] = [str(z) for z in (T.get("points") or [])][:6]
            if dev(x):
                for mo, (n, t, d) in md.items():
                    q = await qv(n, t, d); nb40 = near("v1", q, x["day"], x["stem"], 40)
                    for kk, pp in SWEEP: o[f"RC|{mo}|k{kk}p{pp}"] = await condb(n, t, d, "v1", nb40[:kk], "RC", pp, cap=16000)
            C[k] = o; csave()
        o = C[k]; res = {"sim1": o["sim1"], "dev": dev(x)}
        l1 = {f"{mo}|{a}": v for mo in md for a, v in (("b20v1", base.get(f"RC|{mo}|b20")), ("b20v2", o.get(f"RC|{mo}|b20v2")), ("c", base.get(f"RC|{mo}|c")), ("d", base.get(f"RC|{mo}|d"))) if v}
        res["P1"] = await adjx(f"adjP1|{x['key']}", x["comments"], base["real|RC"], l1, "RC") if base.get("real|RC") else None
        l2 = {f"{mo}|{a}": o.get(f"RX|{mo}|{a}") for mo in md for a in ("b20", "dep", "const") if o.get(f"RX|{mo}|{a}")}
        res["P2"] = await adjx(f"adjP2|{x['key']}", x["comments"], o["real|RX"], l2, "RX") if o.get("real|RX") else None
        if dev(x):
            l3 = {f"{mo}|k{kk}p{pp}": o.get(f"RC|{mo}|k{kk}p{pp}") for mo in md for kk, pp in SWEEP if o.get(f"RC|{mo}|k{kk}p{pp}")}
            l3.update({f"{mo}|c": base[f"RC|{mo}|c"] for mo in md if base.get(f"RC|{mo}|c")})
            res["P3"] = await adjx(f"adjP3|{x['key']}", x["comments"], base["real|RC"], l3, "RC") if base.get("real|RC") else None
        return x, res
async def run(xs):
    sem = asyncio.Semaphore(5); return await asyncio.gather(*[one(x, sem) for x in xs])
ALL = FIRST + NEW; R = asyncio.run(run(ALL))
def mb(v):
    v = np.array([z for z in v if z is not None and not np.isnan(z)], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
MET = {"p@3": lambda o: float(np.mean(o["lab"][:3])), "prec_all": lambda o: float(np.mean(o["lab"])), "recall": lambda o: o["rec"] if o["rec"] is not None else np.nan, "top1": lambda o: float(o["lab"][0])}
g = lambda o, nm, m: MET[m](o[nm]) if o and o.get(nm) and o[nm]["lab"] else np.nan
def table(rows, part, arms, ref, mets, paths=("page", "ph")):
    out = {}
    for mo in paths:
        o_ = {}
        for m in mets:
            o_[m] = {a: mb([g(r[part], f"{mo}|{a}", m) for r in rows]) for a in arms}
            for a in arms:
                for b in ref:
                    if a != b: o_[m][f"{a} - {b}"] = mb([g(r[part], f"{mo}|{a}", m) - g(r[part], f"{mo}|{b}", m) for r in rows])
        out[mo] = o_
    return out
res = {"design": __doc__.split("\n    python")[0]}
# (1)
nb = {"v1": len(RBM), "v2": len(M2), "v2_days": [M2[0]["day"], M2[-1]["day"]], "v2_new_rows": sum(not m.get("in_v1") for m in M2),
      "themes_per_launch_v1": round(float(np.mean([len(m["themes"]) for m in RBM])), 2), "themes_per_launch_v2": round(float(np.mean([len(m["themes"]) for m in M2])), 2)}
thin = {f"{b}|{mo}": round(float(np.mean([(r["sim1"].get(f"{b}|{mo}") or 0) < THR[mo] for _, r in R if r["sim1"].get(f"{b}|{mo}") is not None])) * 100, 1) for b in ("v1", "v2") for mo in ("ph", "page")}
res["part1_bank"] = {"bank": nb, "thin_share_pct_below_recipe_threshold": thin, "concerns": table([r for _, r in R], "P1", ("b20v1", "b20v2", "c", "d"), ("b20v1", "c", "d"), ("p@3", "recall", "top1"))}
# (2)
res["part2_reactions"] = table([r for _, r in R], "P2", ("b20", "dep", "const"), ("dep", "const"), ("prec_all", "p@3", "recall", "top1"))
# (3) sweep on dev, choose by mean p@3 over both paths
D_ = [r for x, r in R if r["dev"] and r.get("P3")]
sc = {f"k{kk}p{pp}": float(np.nanmean([g(r["P3"], f"{mo}|k{kk}p{pp}", "p@3") for r in D_ for mo in ("page", "ph")])) for kk, pp in SWEEP}
best = max(sc, key=sc.get); res["part3_sweep_dev"] = {"n_dev": len(D_), "p@3 mean over paths": {k_: round(v * 100, 1) for k_, v in sc.items()}, "chosen": best,
       "chosen - k20p4 (dev, pooled paths)": mb([g(r["P3"], f"{mo}|{best}", "p@3") - g(r["P3"], f"{mo}|k20p4", "p@3") for r in D_ for mo in ("page", "ph")])}
json.dump(res, open(os.path.join(OUTX, "b20_ext_stage1.json"), "w"), indent=1, default=float); print(json.dumps(res["part3_sweep_dev"]), flush=True)
kb, pb = map(int, re.match(r"k(\d+)p(\d+)", best).groups())
async def conf(x, sem):
    async with sem:
        base = C[f"lists|{x['key']}"]; md = {m: v for m, v in modes(x).items() if v[2].strip()}; k = f"conf|{best}|{x['key']}"
        if k not in C:
            o = {}
            for mo, (n, t, d) in md.items():
                q = await qv(n, t, d); o[f"RC|{mo}|chosen"] = await condb(n, t, d, "v1", near("v1", q, x["day"], x["stem"], kb), "RC", pb, cap=16000)
            C[k] = o; csave()
        l4 = {f"{mo}|{a}": v for mo in md for a, v in (("chosen", C[k].get(f"RC|{mo}|chosen")), ("b20", base.get(f"RC|{mo}|b20")), ("c", base.get(f"RC|{mo}|c")), ("d", base.get(f"RC|{mo}|d"))) if v}
        return await adjx(f"adjP4|{best}|{x['key']}", x["comments"], base["real|RC"], l4, "RC") if base.get("real|RC") else None
async def runc(xs):
    sem = asyncio.Semaphore(5); return await asyncio.gather(*[conf(x, sem) for x in xs])
RC4 = [{"P4": o} for o in asyncio.run(runc([x for x in ALL if not dev(x)])) if o]
res["part3_confirm_half"] = {"chosen": best, **table(RC4, "P4", ("chosen", "b20", "c", "d"), ("b20", "c", "d"), ("p@3", "recall", "top1"))}
res["est_usd_adjudicator"] = round(USD["usd"], 2); res["est_usd_generation"] = round(USD["gen"], 2)
json.dump(res, open(os.path.join(OUTX, "b20_ext.json"), "w"), indent=1, default=float); print("done", res["est_usd_adjudicator"], res["est_usd_generation"])
