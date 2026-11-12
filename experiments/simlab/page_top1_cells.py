"""Where does the "most likely question" from a URL work? (orchestrator 15:34Z Nov 12; no model calls). The raw-page top-1 question
(page_path run 1 + run 2 RQ_b_raw item 1, page_top1 run 3 arm a = the same item) adjudicated three times; per launch hit = mean over the
3 adjudications; generic = the constant list's first question, same runs. Cells: topic group (first PH topic), price model (the page
read's pricing field; fresh reads did not record it -> unknown), number of real comments, final daily rank group. 95% launch bootstrap.
    python page_top1_cells.py <ph-website worktree> <scratchpad> <page_path out dir>
"""
import os, sys, json, re
WT, SP0, OUTD = sys.argv[1:4]; HERE = os.path.dirname(os.path.abspath(__file__))
PP = open(os.path.join(HERE, "page_path.py")).read(); sys.argv = [sys.argv[0], WT, SP0, OUTD]
exec(PP[:PP.index("async def one(x, sem):")])
rows_ = []
for x in LAUNCH:
    h, gnr = [], []
    for k, n_ in ((f"adj|{x['key']}", "RQ_b_raw"), (f"adj2|{x['key']}", "RQ_b_raw"), (f"adj3|{x['key']}", "RQ_a")):
        o = C.get(k)
        if o and o.get(n_): h.append(float(o[n_][0]))
        cn = "RQ_const"
        if o and o.get(cn): gnr.append(float(o[cn][0]))
    if not h: continue
    tp = (x["topic"] or "").lower()
    grp = "AI / agents" if re.search(r"artificial|\bai\b|agent|llm|gpt", tp) else "dev tools" if re.search(r"developer|github|api|no-code|open source|software engineering", tp) else "productivity" if re.search(r"productiv|task|calendar|notes|slack|email|saas|business", tp) else "consumer / other"
    pr = str(x["read"].get("pricing") or "").lower()
    price = "unknown" if not pr else "free" if re.search(r"\bfree\b", pr) and not re.search(r"paid|\$|pro|premium|subscription|trial|freemium", pr) else "freemium" if re.search(r"freemium|free (plan|tier|trial)|free and", pr) else "paid" if re.search(r"\$|paid|subscription|per month|/mo|premium|pro plan|one-time", pr) else "unknown"
    s = x["key"].split("|", 1)[1]
    rk = float(L[L.id.astype(str) == s]["rank"].iat[0]) if x["key"].startswith("F|") and (L.id.astype(str) == s).any() else float(ns["bys"][s].daily_rank) if s in ns["bys"] else np.nan
    nc = len(x["comments"])
    rows_.append({"hit": np.mean(h), "gen": np.mean(gnr) if gnr else np.nan, "topic": grp, "price": price,
                  "comments": "5-9" if nc < 10 else "10-19" if nc < 20 else "20+", "rank": "#1-5" if rk <= 5 else "6-15" if rk <= 15 else "16+" if rk == rk else "unknown"})
D = pd.DataFrame(rows_); rng2 = np.random.default_rng(0)
def ci(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) < 3: return [round(float(v.mean()) * 100, 1) if len(v) else None, None, None, int(len(v))]
    bs = [v[rng2.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]
res = {"design": __doc__.split("\n    python")[0], "launches": len(D), "all": {"hit": ci(D.hit), "generic": ci(D.gen), "hit - generic": ci(D.hit - D.gen)}}
for col in ("topic", "price", "comments", "rank"):
    res[col] = {}
    for g_, d in D.groupby(col):
        c = ci(d.hit - d.gen); res[col][g_] = {"hit": ci(d.hit), "generic": ci(d.gen), "hit - generic": c, "beats_generic": bool(c[1] is not None and c[1] > 0)}
json.dump(res, open(os.path.join(OUTD, "page_top1_cells.json"), "w"), indent=1, default=float)
print("all", res["all"])
for col in ("topic", "price", "comments", "rank"):
    for g_, v in res[col].items(): print(col, g_, "hit", v["hit"], "generic", v["generic"][0], "diff", v["hit - generic"], "beats" if v["beats_generic"] else "")
