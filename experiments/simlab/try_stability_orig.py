"""Re-score the try_stability reactions with the ORIGINAL try_e2e / reactions_v2 metric (orchestrator 09:30Z Nov 12): truth = up to 8
main themes from identity-free comments (praise included; try_e2e EX prompt), judge = try_e2e JUDGE (a_covered -> recall, b_present ->
precision), gemini-2.5-flash at 0. Reactions as stored by try_stability (comment text; the stored lists lack the 'why' that try_e2e
appended). Launches with >= 5 non-team comments.
    python try_stability_orig.py <ph-website worktree> <scratchpad> <stability dir>
"""
import os, sys, json, re
WT, SP0, SD = sys.argv[1:4]
SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "try_fixes.py")).read().split("\n")
sys.argv = [sys.argv[0], WT, SP0, os.path.join(SP0, "try_fixes")]
exec("\n".join(SRC[:118]) + "\n" + "\n".join(SRC[145:254]))
E2 = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "try_e2e.py")).read()
exec(E2[E2.index('EX = """Below are real user comments'):E2.index("JC = ")])   # original EX + JUDGE prompts
EXo, JUDGEo = EX, JUDGE
C = json.load(open(os.path.join(SD, "cache.json"))); O = {}
ids = sorted({k.split("|")[1] for k in C if k.startswith("run0|")})
async def one(i, sem):
    async with sem:
        if len(truth_c.get(i, [])) < 5: return None
        T = await cj(EXo.format(c="\n".join(f"- {t[:400]}" for t in truth_c[i][:40])), tok=2000)
        tt = [str(x.get("theme")) for x in (T.get("themes") or []) if isinstance(x, dict) and x.get("theme")][:8]
        out = {"n_themes": len(tt)}
        for arm, key in (("page_run1", f"run0|{i}"), ("page_run2", f"run1|{i}"), ("ph", f"paste_ph|{i}")):
            rr = (C.get(key) or {}).get("reactions")
            if tt and rr:
                a = await cj(JUDGEo.format(a=num(tt), b=num(rr)), tok=800)
                ac, bp = [tb(x) for x in a.get("a_covered", [])], [tb(x) for x in a.get("b_present", [])]
                if len(ac) == len(tt) and len(bp) == len(rr): out[arm] = (float(np.mean(ac)), float(np.mean(bp)))
        return out
async def main():
    sem = asyncio.Semaphore(6); return await asyncio.gather(*[one(i, sem) for i in ids])
R = [x for x in asyncio.run(main()) if x]
def mb(v):
    v = np.array(v, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
res = {"design": __doc__.split("\n    python")[0], "launches_with_truth": len(R)}
for arm in ("page_run1", "page_run2", "ph"):
    res[arm] = {"recall": mb([x[arm][0] for x in R if arm in x]), "precision": mb([x[arm][1] for x in R if arm in x])}
j = [x for x in R if "page_run1" in x and "ph" in x]
res["page - ph (paired)"] = {"recall": mb([x["page_run1"][0] - x["ph"][0] for x in j]), "precision": mb([x["page_run1"][1] - x["ph"][1] for x in j])}
json.dump(res, open(os.path.join(SD, "orig_metric.json"), "w"), indent=1); print(json.dumps(res, indent=1))
