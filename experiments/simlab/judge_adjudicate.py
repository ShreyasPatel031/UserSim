"""Which judge is right? (orchestrator 09:59Z Nov 12). Items from judge_reliability.py (96 launches, extraction 1): every simulated
reaction (b_present: lenient JUDGE vs strict JUDGE2) and every real theme (a_covered). All items are adjudicated, not a sample, by
gemini-2.5-pro at temperature 0 (thinking budget 128), one call per launch, seeing the REAL COMMENTS (up to 40, 300 chars) as well as the
theme labels. Rubric: SAME_POINT (a reader would say the simulated reaction makes the same specific observation / complaint / question as a
real comment) / SAME_TOPIC (same feature area or generic sentiment, different point) / UNRELATED. Run 2 on the first 48 launches for
self-agreement; the generic constant list adjudicated on the same 48 (blinded, own call). Examples from the disagreement cell go to the
bucket only (they quote real-comment themes).
    python judge_adjudicate.py <ph-website worktree> <scratchpad> <reliab dir>
"""
import os, sys, json
WT, SP0, RD = sys.argv[1:4]; HERE = os.path.dirname(os.path.abspath(__file__))
JR = open(os.path.join(HERE, "judge_reliability.py")).read()
sys.argv = [sys.argv[0], WT, SP0, RD]
exec(JR[:JR.index('CF = os.path.join(OUTD, "cache_rel.json")')])   # rows (set, id, comments, simulated list), cj, CONST
REL = json.load(open(os.path.join(RD, "cache_rel.json")))
CA = os.path.join(RD, "cache_adj.json"); A = json.load(open(CA)) if os.path.exists(CA) else {}; asave = lambda: json.dump(A, open(CA, "w"))
ADJ = """You are adjudicating whether simulated user reactions to a product launch match what REAL users said. Use the rubric exactly:
SAME_POINT  = a reader would say the item makes the same specific observation, complaint, request or question as at least one real comment.
SAME_TOPIC  = same feature area or the same generic sentiment (e.g. both are general praise, both mention pricing), but a different specific point.
UNRELATED   = neither.
REAL COMMENTS (what actual users wrote):
{comments}

REAL THEMES (a summary of the comments above):
{themes}

SIMULATED ITEMS:
{items}

Return JSON {{"items": ["SAME_POINT"|"SAME_TOPIC"|"UNRELATED" per simulated item, judged against the real comments],
"themes": ["SAME_POINT"|"SAME_TOPIC"|"UNRELATED" per real theme: the best match among ALL simulated items]}}"""
LV = {"SAME_POINT": 2, "SAME_TOPIC": 1, "UNRELATED": 0}
USD = {"usd": 0.0}
async def adj(comments, themes, items, key):
    if key in A: return A[key]
    if USD["usd"] > 1.9: return None
    p = ADJ.format(comments="\n".join(f"- {str(t)[:300]}" for t in list(comments)[:40]), themes="\n".join(f"{i+1}. {t}" for i, t in enumerate(themes)),
                   items="\n".join(f"{i+1}. {t}" for i, t in enumerate(items)))
    try:
        raw = await GC.gemini_chat([{"role": "user", "content": p}], model="gemini-2.5-pro", temperature=0.0, thinking_budget=128, max_retries=3, max_output_tokens=1500)
        a = GC.extract_json(raw) or {}
    except Exception as e: a = {"err": str(e)[:100]}
    USD["usd"] += len(p) / 4 * 1.25e-6 + (128 + 400) * 10e-6
    it, th = a.get("items") or [], a.get("themes") or []
    out = {"items": [LV.get(str(x).upper(), None) for x in it] if len(it) == len(items) else None, "themes": [LV.get(str(x).upper(), None) for x in th] if len(th) == len(themes) else None}
    A[key] = out; asave(); return out
async def one(k, r, sem):
    async with sem:
        g, s, comments, lst = r; rel = REL.get(f"{g}|{s}")
        if not rel or not rel["ex"][0]["themes"]: return None
        th = rel["ex"][0]["themes"]; o = {"r1": await adj(comments, th, lst, f"r1|{g}|{s}")}
        if k < 48:
            o["r2"] = await adj(comments, th, lst, f"r2|{g}|{s}"); o["const"] = await adj(comments, th, CONST, f"const|{g}|{s}")
        return o
order = [i for i in range(len(rows)) if rows[i][0] == "FRESH"][:24] + [i for i in range(len(rows)) if rows[i][0] == "S300"][:24]
order += [i for i in range(len(rows)) if i not in order]
async def main():
    sem = asyncio.Semaphore(6); outs = await asyncio.gather(*[one(k, rows[i], sem) for k, i in enumerate(order)]); return dict(zip(order, outs))
AD = asyncio.run(main()); print("adjudicated; est usd", round(USD["usd"], 2), flush=True)

# ---------- analysis ----------
recs = []   # item level
for i, o in AD.items():
    if not o or not o["r1"] or o["r1"]["items"] is None: continue
    g, s, comments, lst = rows[i]; ex = REL[f"{g}|{s}"]["ex"][0]; j1, j2 = ex["j1"][0], ex["j2"]
    if not j1 or not j2: continue
    for k, v in enumerate(o["r1"]["items"]):
        recs.append({"set": g, "launch": s, "kind": "b_present", "k": k, "len": j1[1][k], "str": j2[1][k], "adj": v, "adj2": (o.get("r2") or {}).get("items", [None] * 99)[k] if o.get("r2") and o["r2"].get("items") else None})
    if o["r1"]["themes"] is not None:
        for k, v in enumerate(o["r1"]["themes"]):
            recs.append({"set": g, "launch": s, "kind": "a_covered", "k": k, "len": j1[0][k], "str": j2[0][k], "adj": v, "adj2": (o.get("r2") or {}).get("themes", [None] * 99)[k] if o.get("r2") and o["r2"].get("themes") else None})
D = pd.DataFrame(recs).dropna(subset=["adj"]); D["len"] = D["len"].astype(bool); D["str"] = D["str"].astype(bool)
def kap(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float); po = (a == b).mean(); pe = a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean()); return round(float((po - pe) / (1 - pe)), 3)
res = {"design": __doc__.split("\n    python")[0], "est_usd": round(USD["usd"], 2), "items": {}}
for kind in ("b_present", "a_covered"):
    d = D[D.kind == kind]; o = {"n": len(d)}
    cells = {"both_yes": d.len & d["str"], "both_no": ~d.len & ~d["str"], "lenient_yes_strict_no": d.len & ~d["str"], "strict_yes_lenient_no": ~d.len & d["str"]}
    o["cells"] = {c: {"n": int(m.sum()), "SAME_POINT": round(float((d.adj[m] == 2).mean()) * 100, 1) if m.any() else None,
                      "SAME_TOPIC": round(float((d.adj[m] == 1).mean()) * 100, 1) if m.any() else None, "UNRELATED": round(float((d.adj[m] == 0).mean()) * 100, 1) if m.any() else None} for c, m in cells.items()}
    for std, pos in (("same_point", d.adj == 2), ("same_point_or_topic", d.adj >= 1)):
        for jn in ("len", "str"):
            jy = d[jn]; o[f"{jn} vs {std}"] = {"precision": round(float(pos[jy].mean()) * 100, 1), "recall": round(float(jy[pos].mean()) * 100, 1), "kappa": kap(jy, pos)}
    m2 = d.adj2.notna(); o["adjudicator_self"] = {"n": int(m2.sum()), "exact_3level_agree": round(float((d.adj[m2] == d.adj2[m2]).mean()) * 100, 1),
                                                   "kappa_same_point": kap(d.adj[m2] == 2, d.adj2[m2] == 2), "kappa_point_or_topic": kap(d.adj[m2] >= 1, d.adj2[m2] >= 1)}
    res["items"][kind] = o
# headline under each standard (launch means), with the constant list on the 48
rng2 = np.random.default_rng(0)
def mb(v):
    v = np.array(v, float); bs = [v[rng2.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
res["headline"] = {}
for G in ("S300", "FRESH"):
    h = {}
    for std, thr in (("same_point", 2), ("same_topic_or_point", 1)):
        pre = [np.mean(np.array(o["r1"]["items"]) >= thr) for i, o in AD.items() if o and o["r1"] and o["r1"]["items"] and rows[i][0] == G]
        rec = [np.mean(np.array(o["r1"]["themes"]) >= thr) for i, o in AD.items() if o and o["r1"] and o["r1"]["themes"] and rows[i][0] == G]
        cp = [np.mean(np.array(o["const"]["items"]) >= thr) for i, o in AD.items() if o and o.get("const") and o["const"]["items"] and rows[i][0] == G]
        cr = [np.mean(np.array(o["const"]["themes"]) >= thr) for i, o in AD.items() if o and o.get("const") and o["const"]["themes"] and rows[i][0] == G]
        h[std] = {"recall": mb(rec), "precision": mb(pre), "constant_recall": mb(cr) if cr else None, "constant_precision": mb(cp) if cp else None}
    res["headline"][G] = h
json.dump(res, open(os.path.join(RD, "judge_adjudicate.json"), "w"), indent=1, default=float)
# 10 anonymised disagreement examples -> bucket only
ex_ = []
for _, r in D[(D.kind == "b_present") & D.len & ~D["str"]].sample(frac=1, random_state=0).head(10).iterrows():
    i = next(i for i in range(len(rows)) if rows[i][1] == r.launch); lst = rows[i][3]; th = REL[f"{rows[i][0]}|{r.launch}"]["ex"][0]["themes"]
    ex_.append({"simulated": lst[r.k], "real_themes": th, "adjudicator": {2: "SAME_POINT", 1: "SAME_TOPIC", 0: "UNRELATED"}[int(r.adj)]})
json.dump(ex_, open(os.path.join(RD, "disagreement_examples.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=float))
