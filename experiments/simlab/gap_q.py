"""Gap-based page QUESTIONS (orchestrator 04:02Z Nov 13). Pooled 170 of retrieval_rep (page path only), split fixed before the run:
dev = sha1(key) even (same split as b20_ext), confirmation = odd; nothing is tuned (weights fixed below), dev is reported for reference.
(1) 14 question types (fixed list below). Every real question theme of the v1 retrieval bank dated <= Aug 31 (before every test launch) is
    classified into one type or "other" by gemini-2.5-flash-lite (batches of 50; embedding cosine did not separate types: all 0.81-0.88); base rate = share of bank launches with >= 1 question
    of the type.
(2) Per target page: one gemini-2.5-flash call (temperature 0) on name, tagline and the raw page excerpt[:4000] marks each type ANSWERED /
    PARTLY / ABSENT and words one product-specific question per type. Score = base rate x (1.0 absent, 0.4 partly, 0.05 answered);
    top 3 = GAP. GAPDEP = top 2 of GAP + deployed's first question (deduplicated, then deployed's next).
(3) Arms: GAP, GAPDEP, deployed ranked() (c), constant (d), b20 (page) - lists from the replication cache. Strict gemini-2.5-pro judge, one
    pooled call per launch; p@3, recall of the launch's real top-3 questions, top-1; paired launch bootstrap.
    python gap_q.py <ph-website worktree> <scratchpad> <page_path out dir> <rr dir> <bank_v2 dir> <out dir>
"""
import os, sys, json, hashlib
HERE = os.path.dirname(os.path.abspath(__file__)); OUTG = sys.argv[6]
BX = open(os.path.join(HERE, "b20_ext.py")).read(); exec(BX[:BX.index("async def one(x, sem):")])
os.makedirs(OUTG, exist_ok=True)
_i = BX.index("def mb(v):"); exec(BX[_i:BX.index("res = {", _i)])
TYPES = {"pricing": "How much does it cost, what are the pricing plans, is there a free tier or free trial?",
 "platforms": "Is it available on mobile, iOS, Android, Windows, Linux, a browser extension or other platforms?",
 "integrations": "Does it integrate with other tools I use, like Slack, Notion, Google, Zapier or my existing stack?",
 "privacy": "Where does my data go, how is privacy and security handled, is data stored or used for training?",
 "selfhost": "Is it open source, can I self-host it or run it locally or offline?",
 "competitor": "How is this different from or better than a named competitor or existing alternative?",
 "limits": "What are the limits, quotas, usage caps, file sizes or rate limits?",
 "roadmap": "Are you planning to add a specific feature, is it on the roadmap, when will it be available?",
 "api": "Is there an API, SDK, CLI or developer access?",
 "team": "Who is the team behind it, how big is the company, what is the business model or funding?",
 "onboarding": "How do I get started, how long is setup, is there a learning curve or a demo?",
 "accuracy": "How accurate or reliable is it, how does it handle errors, hallucinations or edge cases?",
 "models": "Which AI models or LLMs does it use, can I choose or bring my own model or API key?",
 "language": "Does it support other languages, regions or countries?"}
TN = list(TYPES); TE = await_ = None
CLS = """Classify each user question from a Product Hunt launch into ONE type key, or "other" if none fits.
Types:
{types}
Questions:
{qs}
Return JSON {{"types": ["<type key or other>", ...one per question, same order]}}"""
async def setup():
    rows = [(j, q) for j, m in enumerate(RBM) if m["day"] <= "2026-08-31" for q in ptsb(RBM, j, "RQ")]; lab = []
    sem = asyncio.Semaphore(8)
    async def batch(i):
        k = f"qtype|{i}"
        if k not in C:
            async with sem:
                qs = [q for _, q in rows[i:i + 50]]
                r = (await cj(CLS.format(types="\n".join(f"- {t}: {TYPES[t]}" for t in TN), qs="\n".join(f"{n+1}. {q[:200]}" for n, q in enumerate(qs))), model="gemini-2.5-flash-lite", tok=1500)).get("types") or []
                C[k] = [str(z).strip().lower() for z in r] if len(r) == len(qs) else ["other"] * len(qs)
        return C[k]
    for v in await asyncio.gather(*[batch(i) for i in range(0, len(rows), 50)]): lab += v
    csave(); nl = len({j for j, _ in rows}); hit = {t: set() for t in TN}
    for (j, _), t in zip(rows, lab):
        if t in hit: hit[t].add(j)
    base = {t: len(hit[t]) / max(1, nl) for t in TN}
    return base, {"bank_launches": nl, "questions": len(rows), "assigned_share": round(float(np.mean([t in hit for t in lab])), 3), "classifier": "gemini-2.5-flash-lite, batches of 50"}
BASE, BINFO = asyncio.run(setup()); print("base rates", {t: round(v, 3) for t, v in sorted(BASE.items(), key=lambda z: -z[1])}, BINFO, flush=True)
MARK = """A new product is launching on Product Hunt today. Here is its own web page.
Product: {n} - {t}
Page text:
{d}

For each question type below, say whether the page ANSWERS it (clearly stated), PARTLY answers it, or it is ABSENT from the page, and write
the question a Product Hunt user would ask the makers about THIS product for that type (specific, one sentence).
Types:
{types}
Return JSON {{"types": [{{"type": "<type key>", "status": "ANSWERED"|"PARTLY"|"ABSENT", "question": "..."}}, ...one per type, same order]}}"""
W = {"ABSENT": 1.0, "PARTLY": 0.4, "ANSWERED": 0.05}
async def gap(x):
    k = f"gapq|{x['key']}"
    if k in C:
        if not C[k]: return C[k]
        return {"ranked": sorted([(BASE[tk] * W.get(st_.upper(), 0.4), tk, st_, q) for _, tk, st_, q in C[k]["ranked"]], key=lambda z: -z[0])}
    rd = x["read"]; n, t, d = rd.get("name") or x["ph"][0], rd.get("tagline") or "", rd.get("page_excerpt") or ""
    if not d.strip(): C[k] = None; return None
    pr = MARK.format(n=n, t=t, d=d[:4000], types="\n".join(f"- {tk}: {TYPES[tk]}" for tk in TN)); USD["gen"] += len(pr) / 4 * 0.3e-6 + 900 * 2.5e-6
    j = (await cj(pr, tok=2500)).get("types") or []; out = []
    for it in j:
        tk = str(it.get("type", "")).strip().lower()
        if tk in BASE and it.get("question"): out.append((BASE[tk] * W.get(str(it.get("status", "")).upper(), 0.4), tk, str(it.get("status")), str(it["question"])))
    out.sort(key=lambda z: -z[0]); C[k] = {"ranked": out}; csave(); return C[k]
async def one(x, sem):
    async with sem:
        base = C[f"lists|{x['key']}"]; g = await gap(x)
        if not g or not g["ranked"] or not base.get("real|RQ"): return x, None, g
        G = [q for _, _, _, q in g["ranked"][:3]]; dep = base.get("RQ|page|c") or []
        GD = G[:2] + [q for q in dep if q not in G[:2]][:1]
        lists = {"gap": G, "gapdep": GD, "c": dep, "d": base.get("RQ|page|d"), "b20": base.get("RQ|page|b20")}
        lists = {f"page|{a}": v for a, v in lists.items() if v}
        return x, await adjx(f"adjGQ|{x['key']}", x["comments"], base["real|RQ"], lists, "RQ"), g
async def run(xs):
    sem = asyncio.Semaphore(5); return await asyncio.gather(*[one(x, sem) for x in xs])
R = [(x, o, gg) for x, o, gg in asyncio.run(run(FIRST + NEW)) if o]
res = {"design": __doc__.split("\n    python")[0], "base_rates": {t: round(v, 3) for t, v in sorted(BASE.items(), key=lambda z: -z[1])}, "bank": BINFO,
       "absent_share_by_type": {t: round(float(np.mean([any(tk == t and s.upper() == "ABSENT" for _, tk, s, _ in gg["ranked"]) for _, _, gg in R])), 3) for t in TN}}
for sub, f in (("confirmation", lambda x: not dev(x)), ("dev", dev), ("all", lambda x: True)):
    rows = [{"P": o} for x, o, _ in R if f(x)]
    res[sub] = table(rows, "P", ("gap", "gapdep", "c", "d", "b20"), ("c", "d", "b20"), ("p@3", "recall", "top1"), paths=("page",))["page"]
    res[sub]["n"] = len(rows)
res["est_usd_adjudicator"] = round(USD["usd"], 2); res["est_usd_generation"] = round(USD["gen"], 2)
json.dump(res, open(os.path.join(OUTG, "gap_q.json"), "w"), indent=1, default=float)
for sub in ("confirmation", "dev", "all"):
    print(sub, res[sub]["n"], {m: {a: v for a, v in d.items() if a in ("gap", "gapdep", "c", "d", "b20", "gap - c", "gapdep - c", "gap - d")} for m, d in res[sub].items() if m != "n"})
print("usd", res["est_usd_adjudicator"], res["est_usd_generation"])
