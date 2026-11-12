"""Does the pasted-description top-1 question / concern depend on how much is pasted? (orchestrator 16:34Z Nov 12; no model calls).
PH-description top-1 items from page_path run 1 and run 2 adjudications (mean per launch); generic = the constant first item, same runs.
Bins: description words (<40, 40-100, 100-200, 200+); whether it names pricing / integrations / a target user. 95% launch bootstrap.
    python paste_length.py <ph-website worktree> <scratchpad> <page_path out dir>
"""
import os, sys, json, re
WT, SP0, OUTD = sys.argv[1:4]; HERE = os.path.dirname(os.path.abspath(__file__))
PP = open(os.path.join(HERE, "page_path.py")).read(); sys.argv = [sys.argv[0], WT, SP0, OUTD]
exec(PP[:PP.index("async def one(x, sem):")])
PRICE = re.compile(r"(?i)\bpric|\bfree\b|\$\d|per month|/mo\b|subscription|plan\b|trial"); INTEG = re.compile(r"(?i)integrat|works with|connects? (to|with)|plugin|extension|\bapi\b|slack|notion|zapier|github|google")
USER = re.compile(r"(?i)\bfor (teams|developers|founders|designers|marketers|creators|students|freelancers|startups|businesses|anyone|people|users|small)|built for|designed for|whether you")
rows_ = []
for x in LAUNCH:
    d = x["ph"][2] or ""; w = len(d.split()); r = {"words": w, "price": bool(PRICE.search(d)), "integ": bool(INTEG.search(d)), "user": bool(USER.search(d))}
    for kind in ("RQ", "RC"):
        h, g = [], []
        for k in (f"adj|{x['key']}", f"adj2|{x['key']}"):
            o = C.get(k)
            if o and o.get(f"{kind}_c_ph"): h.append(float(o[f"{kind}_c_ph"][0]))
            if o and o.get(f"{kind}_const"): g.append(float(o[f"{kind}_const"][0]))
        r[f"{kind}_hit"] = np.mean(h) if h else np.nan; r[f"{kind}_gen"] = np.mean(g) if g else np.nan
    rows_.append(r)
D = pd.DataFrame(rows_); D["len"] = pd.cut(D.words, [-1, 39, 100, 200, 10**6], labels=["<40", "40-100", "100-200", "200+"]); rng2 = np.random.default_rng(0)
def ci(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) < 3: return [round(float(v.mean()) * 100, 1) if len(v) else None, None, None, int(len(v))]
    bs = [v[rng2.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), int(len(v))]
res = {"design": __doc__.split("\n    python")[0], "launches": len(D), "words_median": float(D.words.median())}
for kind, lab in (("RQ", "question"), ("RC", "concern")):
    o = {"all": {"hit": ci(D[f"{kind}_hit"]), "generic": ci(D[f"{kind}_gen"]), "diff": ci(D[f"{kind}_hit"] - D[f"{kind}_gen"])}}
    for col in ("len", "price", "integ", "user"):
        for g_, d in D.groupby(col, observed=True): o[f"{col}={g_}"] = {"hit": ci(d[f"{kind}_hit"]), "generic": ci(d[f"{kind}_gen"]), "diff": ci(d[f"{kind}_hit"] - d[f"{kind}_gen"])}
    res[lab] = o
json.dump(res, open(os.path.join(OUTD, "paste_length.json"), "w"), indent=1, default=float)
print("n", len(D), "median words", D.words.median(), D.len.value_counts().to_dict())
for lab in ("question", "concern"):
    for k, v in res[lab].items(): print(lab, k, "hit", v["hit"], "gen", v["generic"][0], "diff", v["diff"])
