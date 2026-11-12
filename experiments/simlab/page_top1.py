"""Raise the page path's single most likely question / concern (orchestrator 14:34Z Nov 12). Same 70 launches as page_path.py, top-1
only, one new gemini-2.5-pro adjudication per launch (all arms pooled, blinded).
  a  current recipe: ranked() on the raw page excerpt (top item; from page_path's cache)
  b  ranked() on the raw excerpt + the page's own pricing / FAQ / docs / integration / limits text from the stored HTML, marked as
     already answered on the page (fresh: the Nov 12 re-fetch; held: the Oct 25 live fetch)
  c  self-consistency: 5 samples (flash-lite, temperature 0.7) of the most likely question / concern, then a flash call picks the one
     that recurs most
  d  b + c.   control: the constant list's first item.
    python page_top1.py <ph-website worktree> <scratchpad> <page_path out dir>
"""
import os, sys, json, re, html as _h
WT, SP0, OUTD = sys.argv[1:4]; HERE = os.path.dirname(os.path.abspath(__file__))
PP = open(os.path.join(HERE, "page_path.py")).read(); sys.argv = [sys.argv[0], WT, SP0, OUTD]
exec(PP[:PP.index("async def one(x, sem):")])
HT = {}
for l in open(os.path.join(SP0, "band_v2/fresh_html.jsonl")):
    x = json.loads(l)
    if x.get("html"): HT[x["id"]] = x["html"]
for l in open(os.path.join(SP0, "fame/sites.jsonl")):
    if '"live"' not in l[:200]: continue
    x = json.loads(l)
    if x.get("src") == "live" and x.get("html"): HT.setdefault(str(x["id"]), x["html"])
KW = re.compile(r"(?i)pric|plan|free|trial|faq|question|integrat|api|docs|limit|support|privacy|security|export|import|team|enterprise")
def answers(h):
    body = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", h or ""); body = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|section|tr|dt|dd)>", "\n", body)
    lines = [" ".join(_h.unescape(re.sub(r"<[^>]+>", " ", t)).split()) for t in body.split("\n")]
    keep = [t for t in lines if 20 <= len(t) <= 300 and KW.search(t)]; return " | ".join(dict.fromkeys(keep))[:900]
lid = lambda x: x["key"].split("|", 1)[1] if x["key"].startswith("F|") else str(bys[x["key"].split("|", 1)[1]].Index if False else ns["bys"][x["key"].split("|", 1)[1]].id)
ONE = {"questions": """A new product is launching on Product Hunt today.
Product: {n} - {t}
{d}
What is the single question a user is most likely to ask the makers in the launch comments? Be specific to this product. Return JSON {{"item": "..."}}""",
       "concerns": """A new product is launching on Product Hunt today.
Product: {n} - {t}
{d}
What is the single concern, objection or feature request a user is most likely to raise in the launch comments? Be specific. Return JSON {{"item": "..."}}"""}
PICK = """Below are {k} independent guesses at the {what} users will raise about a product launch. Which point recurs most (the same point
across guesses)? Return that point as one sentence. Return JSON {{"item": "..."}}
{g}"""
async def sc(n, t, d, kind):
    g = [(await cj(ONE[kind].format(n=n, t=t, d=d[:1500]), model="gemini-2.5-flash-lite", tok=200, temp=0.7)).get("item") for _ in range(5)]
    g = [str(x) for x in g if x]
    if not g: return None
    return (await cj(PICK.format(k=len(g), what="question" if kind == "questions" else "concern", g="\n".join(f"- {x}" for x in g)), tok=200)).get("item")
async def one(x, sem):
    async with sem:
        k = f"top1|{x['key']}"
        if k not in C:
            rd = x["read"]; n, t = rd.get("name") or x["ph"][0], rd.get("tagline") or ""; raw = rd.get("page_excerpt") or ""
            ans = answers(HT.get(lid(x), "")); aug = raw[:800] + (f"\nAlready answered on the product's own page (pricing / FAQ / docs): {ans[:600]}" if ans else "")
            out = {"has_answers": bool(ans)}
            for kind, pre in (("concerns", "RC"), ("questions", "RQ")):
                base = C.get(f"lists|{x['key']}", {}).get(f"{pre}_b_raw") or []
                out[f"{pre}_a"] = base[:1]
                out[f"{pre}_b"] = (await ranked(n, t, aug, kind, x["day"]))[0][:1] if ans else base[:1]
                cc = await sc(n, t, "Description: " + raw, kind); out[f"{pre}_c"] = [cc] if cc else []
                dd = await sc(n, t, "Description: " + aug, kind) if ans else cc; out[f"{pre}_d"] = [dd] if dd else []
                out[f"{pre}_const"] = (CONST_C if pre == "RC" else CONST_Q)[:1]
            C[k] = out; csave()
        L_ = {n_: v for n_, v in C[k].items() if isinstance(v, list) and v}
        return x, C[k], await adjudicate(f"adj3|{x['key']}", x["comments"], L_)
async def main():
    sem = asyncio.Semaphore(5); return await asyncio.gather(*[one(x, sem) for x in LAUNCH])
R = [(x, m, o) for x, m, o in asyncio.run(main()) if o]
def mb(v):
    v = np.array([z for z in v if z is not None and not np.isnan(z)], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
g = lambda o, n_: float(o[n_][0]) if o.get(n_) else np.nan
res = {"design": __doc__.split("\n    python")[0], "launches": len(R), "with_page_answers": sum(m["has_answers"] for _, m, _ in R), "est_usd_adjudicator": round(USD["usd"], 2)}
for pre, kind in (("RQ", "questions"), ("RC", "concerns")):
    o_ = {arm: mb([g(o, f"{pre}_{arm}") for _, _, o in R]) for arm in ("a", "b", "c", "d", "const")}
    for arm in ("b", "c", "d"): o_[f"{arm} - a"] = mb([g(o, f"{pre}_{arm}") - g(o, f"{pre}_a") for _, _, o in R])
    for arm in ("a", "b", "c", "d"): o_[f"{arm} - const"] = mb([g(o, f"{pre}_{arm}") - g(o, f"{pre}_const") for _, _, o in R])
    o_["b - a, launches with page answers"] = mb([g(o, f"{pre}_b") - g(o, f"{pre}_a") for _, m, o in R if m["has_answers"]])
    res[kind] = o_
json.dump(res, open(os.path.join(OUTD, "page_top1.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
