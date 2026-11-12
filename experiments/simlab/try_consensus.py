"""Consensus and temperature-0 outputs for /try (orchestrator 09:30Z Nov 12, A + B). Fresh page-read launches with >= 5 non-team comments
(up to 36), through the site's code. ORIGINAL metric throughout: truth = up to 8 main themes (try_e2e EX), judge = try_e2e JUDGE
(recall = a_covered, precision = b_present), reactions formatted "comment (why)" as in try_e2e; ranked lists p@3 with JC / JQ.
  read: step_page with the read at temperature 0 (the measured free fix), analysis reused for every arm via new_run
  reactions: 4 runs at the site's temperature (0.3) + 2 runs at temperature 0
  consensus: themes (gemini-embedding clusters, cosine >= 0.80) appearing in >= 2 / all 3 of runs 1-3, kept in run-1 order then by count
  stability: judge agreement (B items matching A) for run1 vs run2, temp0 vs temp0, consensus(1,2,3) vs consensus(2,3,4)
  ranked concerns / questions (first 30): 3 runs at 0.3 + 1 at 0; consensus = cluster frequency over 3 runs; p@3 vs single run
  control: a hand-picked generic constant list of 6 typical launch-comment reactions
    python try_consensus.py <ph-website worktree> <scratchpad> <out dir>
"""
import os, sys, json, re, contextvars
WT, SP0, OUTD = sys.argv[1:4]
os.environ["TRY_GLOBAL_DAY"] = "100000"; os.environ["TRY_PER_IP_DAY"] = "100000"; os.environ["TRY_PER_IP_HOUR"] = "100000"
SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "try_fixes.py")).read().split("\n")
sys.argv = [sys.argv[0], WT, SP0, os.path.join(SP0, "try_fixes")]
exec("\n".join(SRC[:118]) + "\n" + "\n".join(SRC[145:254]))
E2 = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "try_e2e.py")).read()
exec(E2[E2.index('EX = """Below are real user comments'):E2.index("JC = ")]); EXo, JUDGEo = EX, JUDGE
os.makedirs(OUTD, exist_ok=True); CF = os.path.join(OUTD, "cache2.json"); C = json.load(open(CF)) if os.path.exists(CF) else {}
csave = lambda: json.dump(C, open(CF, "w"))
T0V = contextvars.ContextVar("t0", default=False); _gc = GC.gemini_chat
async def _gc0(*a, **k):
    if T0V.get(): k["temperature"] = 0.0
    return await _gc(*a, **k)
GC.gemini_chat = _gc0
CONST = ["Congrats on the launch!", "How is this different from existing alternatives?", "What does the pricing look like?",
         "Does it integrate with the tools I already use?", "The interface looks clean and easy to use.", "Is there a free plan or trial?"]
JR = """List A and list B are short simulated user reactions to a product launch. For each item in B, does it raise the same specific point as
some item in A (same specific praise, concern or question, not merely the same broad area)? Return JSON {{"b_matches": [true/false per B item]}}
A:
{a}
B:
{b}"""
rt = lambda rx: [f"{x.get('comment', '')} ({x.get('why', '')})" for x in (rx or {}).get("reactions", [])]
okr = [r for r in L.itertuples() if isinstance(K.get(f"p|{r.id}"), dict) and "read" in K[f"p|{r.id}"] and len(truth_c.get(r.id, [])) >= 5]
S = sorted(okr, key=lambda r: r.id)[:36]; print("launches", len(S), flush=True)

async def gen_one(r, sem):
    async with sem:
        key = f"gen|{r.id}"
        if key in C: return C[key]
        out = {}
        try:
            t = T0V.set(True)
            try: pg = await try_sim.step_page(fix(U[r.id]), "10.3.%d.%d" % (len(C) % 250, 3)); a = pg["analysis"]
            finally: T0V.reset(t)
            out["read"] = {k: a.get(k) for k in ("name", "tagline", "summary", "topics", "page_excerpt")}
            out["react"] = [rt(await try_sim.step_reactions(try_sim.new_run(a))) for _ in range(4)]
            t = T0V.set(True)
            try: out["react_t0"] = [rt(await try_sim.step_reactions(try_sim.new_run(a))) for _ in range(2)]
            finally: T0V.reset(t)
        except Exception as e: out["fail"] = str(e)[:160]
        C[key] = out; csave(); return out
async def g_all():
    sem = asyncio.Semaphore(4); return await asyncio.gather(*[gen_one(r, sem) for r in S])
G = asyncio.run(g_all()); print("generated", sum("fail" not in g for g in G), flush=True)

async def consensus(runs, need):
    items = [(t, k) for k, rr in enumerate(runs) for t in rr]
    if not items: return []
    X = await emb([t.split(" (")[0] for t, _ in items]); SS = X @ X.T; used = np.zeros(len(items), bool); out = []
    for i in range(len(items)):
        if used[i]: continue
        m = (SS[i] >= 0.80) & ~used; ks = {items[j][1] for j in np.flatnonzero(m)}
        if len(ks) >= need: out.append((items[i][0], len(ks), i))
        used |= m
    return [t for t, _, _ in sorted(out, key=lambda x: (-x[1], x[2]))][:6]

async def judge_rp(tt, cand):
    if not tt or not cand: return None
    a = await cj(JUDGEo.format(a=num(tt), b=num(cand)), tok=800); ac, bp = [tb(x) for x in a.get("a_covered", [])], [tb(x) for x in a.get("b_present", [])]
    return (float(np.mean(ac)), float(np.mean(bp))) if len(ac) == len(tt) and len(bp) == len(cand) else None
async def agree(A, B):
    if not A or not B: return None
    bm = (await cj(JR.format(a=num(A), b=num(B)), tok=300)).get("b_matches"); bm = [tb(x) for x in bm] if isinstance(bm, list) else None
    return float(np.mean(bm)) if bm and len(bm) == len(B) else None

async def score_one(r, g, sem):
    async with sem:
        key = f"score|{r.id}"
        if key in C: return C[key]
        if "fail" in g: return None
        T = await cj(EXo.format(c="\n".join(f"- {t[:400]}" for t in truth_c[r.id][:40])), tok=2000)
        tt = [str(x.get("theme")) for x in (T.get("themes") or []) if isinstance(x, dict) and x.get("theme")][:8]
        R_ = g["react"]; c2 = await consensus(R_[:3], 2); c3 = await consensus(R_[:3], 3); c2b = await consensus(R_[1:4], 2)
        out = {"n_c2": len(c2), "n_c3": len(c3), "truth": {"critical": (T.get("critical") or [])[:6], "questions": (T.get("questions") or [])[:6]}}
        for arm, lst in (("single", R_[0]), ("single_run2", R_[1]), ("temp0", g["react_t0"][0]), ("cons2", c2), ("cons3", c3), ("const", CONST)):
            out[arm] = await judge_rp(tt, lst)
        out["agree_single"] = await agree(R_[0], R_[1]); out["agree_temp0"] = await agree(g["react_t0"][0], g["react_t0"][1]); out["agree_cons2"] = await agree(c2, c2b)
        C[key] = out; csave(); return out
async def s_all():
    sem = asyncio.Semaphore(6); return await asyncio.gather(*[score_one(r, g, sem) for r, g in zip(S, G)])
SC = asyncio.run(s_all()); print("scored", flush=True)

# ranked concerns / questions: 3 runs at 0.3 + 1 at 0 (first 30)
async def rq_one(r, g, s, sem):
    async with sem:
        key = f"rq|{r.id}"
        if key in C: return C[key]
        if "fail" in g or not s: return None
        a = g["read"]; d = (a.get("summary") or "") + " " + (a.get("page_excerpt") or ""); out = {}
        for kind, JP, tr in (("concerns", JC, s["truth"]["critical"]), ("questions", JQ, s["truth"]["questions"])):
            runs = [(await ranked(a["name"], a.get("tagline") or "", d, kind, r.day))[0] for _ in range(3)]
            t = T0V.set(True)
            try: t0 = (await ranked(a["name"], a.get("tagline") or "", d, kind, r.day))[0]
            finally: T0V.reset(t)
            # consensus: cluster items over 3 runs, rank by number of runs then mean position
            items = [(x, k, p) for k, rr in enumerate(runs) for p, x in enumerate(rr)]; X = await emb([x for x, _, _ in items]); SS = X @ X.T
            used = np.zeros(len(items), bool); cl = []
            for i in range(len(items)):
                if used[i]: continue
                m = (SS[i] >= 0.80) & ~used; js = np.flatnonzero(m); cl.append((items[i][0], len({items[j][1] for j in js}), np.mean([items[j][2] for j in js]))); used |= m
            cons = [x for x, _, _ in sorted(cl, key=lambda c: (-c[1], c[2]))]
            out[kind] = {"single": await judge(JP, tr, runs[0]), "single_run2": await judge(JP, tr, runs[1]), "temp0": await judge(JP, tr, t0), "cons": await judge(JP, tr, cons),
                         "agree_single": await agree(runs[0][:3], runs[1][:3])}
        C[key] = out; csave(); return out
async def r_all():
    sem = asyncio.Semaphore(4); return await asyncio.gather(*[rq_one(r, g, s, sem) for r, g, s in list(zip(S, G, SC))[:30]])
RQ = asyncio.run(r_all())

def mb(v):
    v = np.array([x for x in v if x is not None and not np.isnan(x)], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
V = [s for s in SC if s]; res = {"design": __doc__.split("\n    python")[0], "launches": len(V), "reactions": {}, "ranked": {}}
for arm in ("single", "single_run2", "temp0", "cons2", "cons3", "const"):
    res["reactions"][arm] = {"recall": mb([s[arm][0] for s in V if s.get(arm)]), "precision": mb([s[arm][1] for s in V if s.get(arm)])}
for arm in ("single_run2", "temp0", "cons2", "cons3", "const"):
    j = [s for s in V if s.get(arm) and s.get("single")]
    res["reactions"][f"{arm} - single (paired)"] = {"recall": mb([s[arm][0] - s["single"][0] for s in j]), "precision": mb([s[arm][1] - s["single"][1] for s in j])}
res["reactions"]["list_length"] = {"cons2": round(float(np.mean([s["n_c2"] for s in V])), 1), "cons3": round(float(np.mean([s["n_c3"] for s in V])), 1), "single": 6}
res["reactions"]["stability"] = {k: mb([s[k] for s in V]) for k in ("agree_single", "agree_temp0", "agree_cons2")}
Q = [q for q in RQ if q]
for kind in ("concerns", "questions"):
    d = {arm: mb([q[kind][arm][0] for q in Q if q[kind].get(arm)]) for arm in ("single", "single_run2", "temp0", "cons")}
    for arm in ("temp0", "cons"):
        j = [q for q in Q if q[kind].get(arm) and q[kind].get("single")]; d[f"{arm} - single (paired)"] = mb([q[kind][arm][0] - q[kind]["single"][0] for q in j])
    d["rerun_overlap@3"] = mb([q[kind]["agree_single"] for q in Q]); res["ranked"][kind] = d
json.dump(res, open(os.path.join(OUTD, "try_consensus.json"), "w"), indent=1); print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1))
