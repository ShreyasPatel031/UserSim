"""How reliable are the quoted "what they will say" numbers? (orchestrator 09:50Z Nov 12). Simulated lists held fixed:
  set FRESH: the 36 fresh page-read launches (try_consensus single run, "comment (why)"), comments = try_fixes identity-free truth_c
  set S300 : 60 of the reactions_v2 300 (BEST lists), stratified by comment-volume tertile (seed 0), comments as in reactions_v2
Per launch: truth extraction x3 (reactions_eval TRUTH prompt, flash, temperature 0, as originally run), per extraction the original
JUDGE x3 (flash, 0) + the second judge (reactions_v2 JUDGE2, covered = score 2) x1, + the generic constant list x1 (JUDGE).
Outputs: variance decomposition (launch / extraction / judge) of recall and precision; hierarchical-bootstrap 95% interval of the
headline vs the launch-only interval; item-level Cohen's kappa JUDGE vs JUDGE2 and JUDGE run-to-run; recall / precision by comment
volume and number of themes; chance-corrected (minus the constant list, same extraction + judge); scoring rules (1 extraction x 1
judge; 1 x majority of 3; mean of 3 extractions x 1 judge) with interval width per call.
    python judge_reliability.py <ph-website worktree> <scratchpad> <out dir>
"""
import os, sys, json, re, html, gzip, glob, random
WT, SP0, OUTD = sys.argv[1:4]; os.makedirs(OUTD, exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "try_fixes.py")).read().split("\n")
sys.argv = [sys.argv[0], WT, SP0, os.path.join(SP0, "try_fixes")]
exec("\n".join(SRC[:118]))   # truth_c for the fresh set, cj(), GC
RV = open(os.path.join(HERE, "reactions_v2.py")).read()
JUDGE = RV[RV.index('JUDGE = """'):RV.index('JUDGE2 = """')]; exec(JUDGE); exec(RV[RV.index('JUDGE2 = """'):RV.index("def judge(")])
RE_ = open(os.path.join(HERE, "reactions_eval.py")).read(); exec(RE_[RE_.index('TRUTH = """'):RE_.index("def truth(")])
# S300 comments exactly as reactions_v2 builds them
ns = {}; sys.argv = [sys.argv[0], os.path.join(SP0, "react_site"), os.path.join(SP0, "cf"), os.path.join(SP0, "early/launches"), os.path.join(SP0, "fame/sites.jsonl"), "x", "x", os.path.join(SP0, "react_v2")]
exec(RV[:RV.index("cache_f = os.path.join(OUT")], ns)
com, S300 = ns["com"], ns["S"]
CV2 = json.load(open(os.path.join(SP0, "react_v2/cache_v2.json"))); CC = json.load(open(os.path.join(SP0, "stability/cache2.json")))
CONST = ["Congrats on the launch!", "How is this different from existing alternatives?", "What does the pricing look like?",
         "Does it integrate with the tools I already use?", "The interface looks clean and easy to use.", "Is there a free plan or trial?"]
rows = []
for k, v in CC.items():
    if k.startswith("gen|") and "react" in v and len(truth_c.get(k[4:], [])) >= 5: rows.append(("FRESH", k[4:], truth_c[k[4:]], v["react"][0]))
cand = [s for s in S300 if CV2.get(f"gen|BEST|{s}")]; vol = pd.Series({s: len(com[s]) for s in cand}); tert = pd.qcut(vol.rank(method="first"), 3, labels=False)
pick = []
for t in range(3): pick += list(pd.Series(tert[tert == t].index).sample(20, random_state=0))
for s in pick: rows.append(("S300", s, list(com[s].values()), CV2[f"gen|BEST|{s}"]))
print("launches", len(rows), {g: sum(r[0] == g for r in rows) for g in ("FRESH", "S300")}, flush=True)
CF = os.path.join(OUTD, "cache_rel.json"); C = json.load(open(CF)) if os.path.exists(CF) else {}
csave = lambda: json.dump(C, open(CF, "w"))
tb = lambda x: x if isinstance(x, bool) else str(x).strip().lower() in ("true", "yes", "1")
num_ = lambda l: "\n".join(f"{i + 1}. {t}" for i, t in enumerate(l))
async def j1(th, lst):
    a = await cj(JUDGE.format(a=num_(th), b=num_(lst)), tok=800); ac, bp = [tb(x) for x in a.get("a_covered", [])], [tb(x) for x in a.get("b_present", [])]
    return (ac, bp) if len(ac) == len(th) and len(bp) == len(lst) else None
async def j2(th, lst):
    a = await cj(JUDGE2.format(a=num_(th), b=num_(lst)), tok=800); rs, fh = a.get("real_scores", []), a.get("forecast_hits", [])
    try: return ([int(x) >= 2 for x in rs], [tb(x) for x in fh]) if len(rs) == len(th) and len(fh) == len(lst) else None
    except Exception: return None
async def one(g, s, comments, lst, sem):
    async with sem:
        key = f"{g}|{s}"
        if key in C: return C[key]
        c = "\n".join(f"- {str(t)[:400]}" for t in list(comments)[:40]); ex = []
        for e in range(3):
            a = await cj(TRUTH.format(c=c), tok=2000); th = [str(t.get("theme")) for t in (a.get("themes") or []) if isinstance(t, dict) and t.get("theme")][:8]
            ex.append({"themes": th, "j1": [await j1(th, lst) for _ in range(3)] if th else [], "j2": await j2(th, lst) if th else None, "const": await j1(th, CONST) if th else None})
        out = {"n_comments": len(comments), "ex": ex}; C[key] = out; csave(); return out
async def main():
    sem = asyncio.Semaphore(8); return await asyncio.gather(*[one(*r, sem) for r in rows])
R = asyncio.run(main()); print("done", flush=True)

def rp(j): return (float(np.mean(j[0])), float(np.mean(j[1]))) if j else (np.nan, np.nan)
res = {"design": __doc__.split("\n    python")[0], "sets": {}}
for G in ("FRESH", "S300", "ALL"):
    idx = [i for i, r in enumerate(rows) if G == "ALL" or r[0] == G]; out = {"launches": len(idx)}
    for m, mi in (("recall", 0), ("precision", 1)):
        Y = np.full((len(idx), 3, 3), np.nan); Y2 = np.full((len(idx), 3), np.nan); YC = np.full((len(idx), 3), np.nan)
        for a, i in enumerate(idx):
            for e, x in enumerate(R[i]["ex"]):
                for jj, j in enumerate(x["j1"]): Y[a, e, jj] = rp(j)[mi]
                Y2[a, e] = rp(x["j2"])[mi]; YC[a, e] = rp(x["const"])[mi]
        ok = ~np.isnan(Y).any(axis=(1, 2)); Y, Y2, YC = Y[ok], Y2[ok], YC[ok]; n = len(Y)
        vj = float(np.nanmean(np.nanvar(Y, axis=2, ddof=1))); me = np.nanmean(Y, axis=2); ve = float(np.nanmean(np.nanvar(me, axis=1, ddof=1)) - vj / 3)
        vl = float(np.nanvar(np.nanmean(me, axis=1), ddof=1) - max(ve, 0) / 3 - vj / 9)
        rng_ = np.random.default_rng(0); B_ = 2000
        def hboot(rule):
            bs = []
            for _ in range(B_):
                L_ = rng_.integers(0, n, n)
                if rule == "1x1": E_ = rng_.integers(0, 3, n); J_ = rng_.integers(0, 3, n); v = Y[L_, E_, J_]
                elif rule == "1xmaj3":   # majority of 3 judges at item level ~ approximated by median of 3 judge scores
                    E_ = rng_.integers(0, 3, n); v = np.nanmedian(Y[L_, E_, :], axis=1)
                elif rule == "3x1": J_ = rng_.integers(0, 3, (n, 3)); v = np.nanmean(Y[L_[:, None], np.arange(3)[None, :], J_], axis=1)
                bs.append(np.nanmean(v))
            return [round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1)]
        lb = [np.nanmean(Y[rng_.integers(0, n, n), 0, 0]) for _ in range(B_)]
        out[m] = {"headline (mean over all)": round(float(np.nanmean(Y)) * 100, 1), "judge2": round(float(np.nanmean(Y2)) * 100, 1),
                  "variance_share": {k: round(max(v_, 0) / (max(vl, 0) + max(ve, 0) + vj) * 100, 1) for k, v_ in (("launch", vl), ("extraction", ve), ("judge", vj))},
                  "sd_points": {"extraction": round(float(np.sqrt(max(ve, 0))) * 100, 1), "judge": round(float(np.sqrt(vj)) * 100, 1)},
                  "interval_launch_only (1 extraction, 1 judge)": [round(float(np.percentile(lb, 2.5)) * 100, 1), round(float(np.percentile(lb, 97.5)) * 100, 1)],
                  "interval_total": {"1x1 (3 calls: extract + judge... per launch = 2)": hboot("1x1"), "1 extraction x majority of 3 judges (4 calls)": hboot("1xmaj3"),
                                     "mean of 3 extractions x 1 judge (6 calls)": hboot("3x1")},
                  "constant_list": round(float(np.nanmean(YC)) * 100, 1), "chance_corrected (minus constant, paired)": round(float(np.nanmean(np.nanmean(Y, 2) - YC)) * 100, 1)}
        # by comment volume / number of themes (judge run 1, extraction 1)
        nc = np.array([R[i]["n_comments"] for i in idx])[ok]; nt = np.array([len(R[i]["ex"][0]["themes"]) for i in idx])[ok]; y0 = Y[:, 0, 0]
        out[m]["by_comments"] = {lab: [round(float(np.nanmean(y0[msk])) * 100, 1), int(msk.sum())] for lab, msk in (("5-9", nc < 10), ("10-19", (nc >= 10) & (nc < 20)), ("20+", nc >= 20))}
        out[m]["by_themes"] = {lab: [round(float(np.nanmean(y0[msk])) * 100, 1), int(msk.sum())] for lab, msk in (("<=5", nt <= 5), ("6-7", (nt >= 6) & (nt <= 7)), ("8", nt >= 8))}
        out[m]["const_by_comments"] = {lab: round(float(np.nanmean(YC[:, 0][msk])) * 100, 1) for lab, msk in (("5-9", nc < 10), ("10-19", (nc >= 10) & (nc < 20)), ("20+", nc >= 20))}
    # item-level kappa
    def kappa(a, b):
        a, b = np.array(a, float), np.array(b, float); po = (a == b).mean(); pe = a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean()); return round(float((po - pe) / (1 - pe)), 3) if pe < 1 else None
    for lab, f in (("a_covered", 0), ("b_present", 1)):
        A1, A2, B1, B2 = [], [], [], []
        for i in idx:
            for x in R[i]["ex"]:
                if x["j1"] and x["j1"][0] and x["j2"]: A1 += x["j1"][0][f]; A2 += x["j2"][f]
                if len(x["j1"]) >= 2 and x["j1"][0] and x["j1"][1]: B1 += x["j1"][0][f]; B2 += x["j1"][1][f]
        out[f"kappa_{lab}"] = {"JUDGE vs JUDGE2": kappa(A1, A2), "JUDGE run1 vs run2": kappa(B1, B2), "items": len(A1)}
    res["sets"][G] = out
json.dump(res, open(os.path.join(OUTD, "judge_reliability.json"), "w"), indent=1, default=float)
print(json.dumps(res["sets"], indent=1, default=float))
