"""Does a DRAFTED launch description close the gap? (orchestrator 12:53Z Nov 12). Same 70 launches and design as page_path.py; input
(e): one flash call writes the maker's launch post (name, tagline, 2-3 paragraph description, maker's voice, no invented facts) from the
raw page excerpt, then ranked concerns / questions on that draft. All arms (a, b, c, e, constant, category) re-adjudicated together in
one new gemini-2.5-pro call per launch so the comparison stays within one run.
    python page_path_draft.py <ph-website worktree> <scratchpad> <page_path out dir>
"""
import os, sys, json
WT, SP0, OUTD = sys.argv[1:4]; HERE = os.path.dirname(os.path.abspath(__file__))
PP = open(os.path.join(HERE, "page_path.py")).read(); sys.argv = [sys.argv[0], WT, SP0, OUTD]
exec(PP[:PP.index("async def one(x, sem):")])
DRAFT = """Here is the text of a product's own web page. Write the launch post its maker would publish on Product Hunt: a name, a tagline
(<= 60 characters) and a 2-3 paragraph description in the maker's voice (what it does, who it is for, how it works, what is new).
Use ONLY facts from the page; do not invent features, numbers, customers or prices.
Page text:
{t}
Return JSON {{"name": "...", "tagline": "...", "description": "..."}}"""
async def one(x, sem):
    async with sem:
        k = f"lists|{x['key']}"; ke = f"draft|{x['key']}"
        if k not in C: return x, None
        if ke not in C:
            rd = x["read"]; d = await cj(DRAFT.format(t=(rd.get("page_excerpt") or "")[:3000]), model="gemini-2.5-flash", tok=1200, temp=0.2)
            n, t, desc = d.get("name") or rd.get("name") or "", d.get("tagline") or "", d.get("description") or ""
            C[ke] = {"draft": [n, t, desc], "RC_e": (await ranked(n, t, desc, "concerns", x["day"]))[0][:3] if desc else [],
                     "RQ_e": (await ranked(n, t, desc, "questions", x["day"]))[0][:3] if desc else []}; csave()
        L_ = {n: v for n, v in {**C[k], "RC_e": C[ke]["RC_e"], "RQ_e": C[ke]["RQ_e"]}.items() if v}
        return x, await adjudicate(f"adj2|{x['key']}", x["comments"], L_)
async def main():
    sem = asyncio.Semaphore(5); return await asyncio.gather(*[one(x, sem) for x in LAUNCH])
R = [(x, o) for x, o in asyncio.run(main()) if o]
def mb(v):
    v = np.array([z for z in v if z is not None and not np.isnan(z)], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
p3 = lambda o, n: float(np.mean(o[n][:3])) if o.get(n) else np.nan
res = {"design": __doc__.split("\n    python")[0], "launches": len(R), "est_usd_adjudicator": round(USD["usd"], 2)}
for kind in ("RC", "RQ"):
    o_ = {arm: mb([p3(o, f"{kind}_{arm}") for _, o in R]) for arm in ("a_read", "b_raw", "c_ph", "e", "const", "cat")}
    for arm in ("b_raw", "c_ph", "e"): o_[f"{arm} - const"] = mb([p3(o, f"{kind}_{arm}") - p3(o, f"{kind}_const") for _, o in R])
    o_["e - b_raw"] = mb([p3(o, f"{kind}_e") - p3(o, f"{kind}_b_raw") for _, o in R]); o_["e - c_ph"] = mb([p3(o, f"{kind}_e") - p3(o, f"{kind}_c_ph") for _, o in R])
    res["concerns" if kind == "RC" else "questions"] = o_
json.dump(res, open(os.path.join(OUTD, "page_path_draft.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
