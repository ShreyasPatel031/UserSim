"""Two-step page path for REACTIONS (orchestrator 01:43Z Nov 13). Same 70 launches as page_path.py. Lists, all through the site's
step_reactions (try_sim.new_run + step_reactions, i.e. the deployed reactions recipe):
  page   the page read as the analysis (current /try URL path)
  two    flash writes a 120-200 word launch-style description from the fetched page text (no invented facts), then the description path
         (analysis with ph_description = the draft, as for pasted text)
  ph     the real PH launch description (pasted path, reference)
  const  generic 6 typical launch comments
Adjudication: one gemini-2.5-pro call per launch (temperature 0, real comments), all items pooled + shuffled; SAME_POINT precision per list.
Paired launch bootstrap.
    python page_react2.py <ph-website worktree> <scratchpad> <page_path out dir>
"""
import os, sys, json
WT, SP0, OUTD = sys.argv[1:4]; HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["TRY_GLOBAL_DAY"] = "100000"; os.environ["TRY_PER_IP_DAY"] = "100000"; os.environ["TRY_PER_IP_HOUR"] = "100000"
PP = open(os.path.join(HERE, "page_path.py")).read(); sys.argv = [sys.argv[0], WT, SP0, OUTD]
exec(PP[:PP.index("async def one(x, sem):")])
CONSTR = ["Congrats on the launch!", "How is this different from existing alternatives?", "What does the pricing look like?",
          "Does it integrate with the tools I already use?", "The interface looks clean and easy to use.", "Is there a free plan or trial?"]
DRAFT = """Here is the text of a product's own web page. Write a 120-200 word launch description for Product Hunt in the maker's voice: what it
does, who it is for, how it works, what is new. Use ONLY facts from the page; do not invent features, numbers, customers or prices.
Page text:
{t}
Return JSON {{"tagline": "<= 60 characters", "description": "..."}}"""
rt = lambda rx: [f"{x.get('comment', '')} ({x.get('why', '')})" for x in (rx or {}).get("reactions", [])][:6]
async def react(a):
    try: return rt(await try_sim.step_reactions(try_sim.new_run(a)))
    except Exception as e: return []
async def one(x, sem):
    async with sem:
        k = f"react2|{x['key']}"
        if k not in C:
            rd = x["read"]; tops = rd.get("topics") or ["Productivity"]; base = {"audience": "", "pricing": "unknown", "strengths": [], "doubts": [], "clarity": None, "url": ""}
            out = {"page": await react({**base, **{kk: rd.get(kk) for kk in ("name", "tagline", "summary", "topics", "audience", "pricing", "strengths", "doubts", "page_excerpt")}})}
            d = await cj(DRAFT.format(t=(rd.get("page_excerpt") or "")[:3000]), model="gemini-2.5-flash", tok=900, temp=0.2)
            desc = d.get("description") or ""; out["draft"] = desc
            if desc:
                out["two"] = await react({**base, "name": rd.get("name") or x["ph"][0], "tagline": d.get("tagline") or rd.get("tagline") or "", "summary": desc[:400],
                                          "topics": tops, "page_excerpt": desc[:2500], "ph_description": desc})
            n, t, dd = x["ph"]
            out["ph"] = await react({**base, "name": n, "tagline": t, "summary": dd[:400], "topics": tops, "page_excerpt": dd[:2500], "ph_description": dd})
            out["const"] = CONSTR; C[k] = out; csave()
        L_ = {n_: v for n_, v in C[k].items() if isinstance(v, list) and v}
        return x, await adjudicate(f"adjr2|{x['key']}", x["comments"], L_)
async def main():
    sem = asyncio.Semaphore(4); return await asyncio.gather(*[one(x, sem) for x in LAUNCH])
R = [(x, o) for x, o in asyncio.run(main()) if o]
def mb(v):
    v = np.array([z_ for z_ in v if z_ is not None and not np.isnan(z_)], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
pr = lambda o, n_: float(np.mean(o[n_])) if o.get(n_) else np.nan
res = {"design": __doc__.split("\n    python")[0], "launches": len(R), "est_usd_adjudicator": round(USD["usd"], 2),
       "precision": {a: mb([pr(o, a) for _, o in R]) for a in ("page", "two", "ph", "const")}}
for a, b in (("two", "page"), ("two", "const"), ("page", "const"), ("ph", "const"), ("two", "ph")):
    res[f"{a} - {b}"] = mb([pr(o, a) - pr(o, b) for _, o in R])
json.dump(res, open(os.path.join(OUTD, "page_react2.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
