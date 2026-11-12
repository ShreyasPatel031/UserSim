"""Consensus by LLM merge (fix for try_consensus.py: gemini-embedding puts every reaction to one product at cosine ~0.94, so cosine
clustering at 0.80 merged whole runs into one theme). Merge prompt (gemini-2.5-flash, temperature 0): the runs' items -> distinct points
with the runs each appears in; consensus = points in >= 2 (or all 3) runs, most runs first, at most 6 (reactions) / 5 (ranked).
Same truth, judges and launches as try_consensus.py (cache2.json); writes try_consensus2.json.
    python try_consensus2.py <ph-website worktree> <scratchpad> <stability dir>
"""
import os, sys, json
WT, SP0, OUTD = sys.argv[1:4]
SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "try_fixes.py")).read().split("\n")
sys.argv = [sys.argv[0], WT, SP0, os.path.join(SP0, "try_fixes")]
exec("\n".join(SRC[:118]) + "\n" + "\n".join(SRC[145:254]))
E2 = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "try_e2e.py")).read()
exec(E2[E2.index('EX = """Below are real user comments'):E2.index("JC = ")]); EXo, JUDGEo = EX, JUDGE
CF = os.path.join(OUTD, "cache2.json"); C = json.load(open(CF)); csave = lambda: json.dump(C, open(CF, "w"))
MERGE = """Below are {k} independent runs of simulated {what} for the same product launch. Merge them into distinct points (two items are the
same point only if they raise the same specific praise / concern / question). For each point give one representative wording and the run
numbers it appears in. Return JSON {{"points": [{{"text": "...", "runs": [1, 2, ...]}}, ...]}}
{runs}"""
JR = """List A and list B are short simulated user reactions to a product launch. For each item in B, does it raise the same specific point as
some item in A (same specific praise, concern or question, not merely the same broad area)? Return JSON {{"b_matches": [true/false per B item]}}
A:
{a}
B:
{b}"""
async def merge(runs, what, need, cap):
    txt = "\n".join(f"Run {k + 1}:\n" + "\n".join(f"- {t}" for t in rr) for k, rr in enumerate(runs))
    P = (await cj(MERGE.format(k=len(runs), what=what, runs=txt), tok=2500)).get("points") or []
    P = [(str(p.get("text")), len(set(int(x) for x in (p.get("runs") or []) if str(x).isdigit()))) for p in P if isinstance(p, dict) and p.get("text")]
    return [t for t, n in sorted(P, key=lambda x: -x[1]) if n >= need][:cap]
async def judge_rp(tt, cand):
    if not tt or not cand: return None
    a = await cj(JUDGEo.format(a=num(tt), b=num(cand)), tok=800); ac, bp = [tb(x) for x in a.get("a_covered", [])], [tb(x) for x in a.get("b_present", [])]
    return (float(np.mean(ac)), float(np.mean(bp))) if len(ac) == len(tt) and len(bp) == len(cand) else None
async def agree(A, B):
    if not A or not B: return None
    bm = (await cj(JR.format(a=num(A), b=num(B)), tok=300)).get("b_matches"); bm = [tb(x) for x in bm] if isinstance(bm, list) else None
    return float(np.mean(bm)) if bm and len(bm) == len(B) else None
ids = sorted(k.split("|")[1] for k in C if k.startswith("gen|") and "react" in C[k])
day = {r.id: r.day for r in L.itertuples()}
async def one(i, sem):
    async with sem:
        key = f"cons2|{i}"
        if key in C: return C[key]
        g, s = C[f"gen|{i}"], C.get(f"score|{i}")
        if not s: return None
        T = await cj(EXo.format(c="\n".join(f"- {t[:400]}" for t in truth_c[i][:40])), tok=2000)
        tt = [str(x.get("theme")) for x in (T.get("themes") or []) if isinstance(x, dict) and x.get("theme")][:8]
        R_ = g["react"]; c2 = await merge(R_[:3], "user reactions", 2, 6); c3 = await merge(R_[:3], "user reactions", 3, 6); c2b = await merge(R_[1:4], "user reactions", 2, 6)
        out = {"n_c2": len(c2), "n_c3": len(c3), "cons2": await judge_rp(tt, c2), "cons3": await judge_rp(tt, c3), "single": await judge_rp(tt, R_[0]),
               "agree_cons2": await agree(c2, c2b), "agree_single": await agree(R_[0], R_[1])}
        C[key] = out; csave(); return out
async def main():
    sem = asyncio.Semaphore(6); return await asyncio.gather(*[one(i, sem) for i in ids])
V = [x for x in asyncio.run(main()) if x]
def mb(v):
    v = np.array([x for x in v if x is not None], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
res = {"design": __doc__.split("\n    python")[0], "launches": len(V), "reactions": {}}
for arm in ("single", "cons2", "cons3"):
    res["reactions"][arm] = {"recall": mb([s[arm][0] for s in V if s.get(arm)]), "precision": mb([s[arm][1] for s in V if s.get(arm)])}
for arm in ("cons2", "cons3"):
    j = [s for s in V if s.get(arm) and s.get("single")]
    res["reactions"][f"{arm} - single (paired, same judge pass)"] = {"recall": mb([s[arm][0] - s["single"][0] for s in j]), "precision": mb([s[arm][1] - s["single"][1] for s in j])}
res["reactions"]["list_length"] = {"cons2": round(float(np.mean([s["n_c2"] for s in V])), 1), "cons3": round(float(np.mean([s["n_c3"] for s in V])), 1)}
res["reactions"]["stability"] = {k: mb([s[k] for s in V]) for k in ("agree_single", "agree_cons2")}
json.dump(res, open(os.path.join(OUTD, "try_consensus2.json"), "w"), indent=1); print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1))
