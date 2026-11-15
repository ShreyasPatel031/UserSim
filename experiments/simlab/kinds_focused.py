"""PREREG_real24_focused.md: FOCUSED vs PANEL vs REAL24 on the same launches."""
import json, sys, os, re, importlib.util, numpy as np, pandas as pd, concurrent.futures as cf
SP = sys.argv[1]; OUT = f"{SP}/kinds"; rng = np.random.default_rng(0); NL = int(os.environ.get("NL", 180)); HERE = "/home/user/UserSim/experiments/simlab"
sys.path.insert(0, "/home/user/UserSim/experiments"); sys.path.insert(0, f"{SP}/phops/experiments/ph_predict"); import llm
from pipeline import warehouse
sp_ = importlib.util.spec_from_file_location("pp", f"{HERE}/persona_prompt.py"); pm = importlib.util.module_from_spec(sp_); sp_.loader.exec_module(pm)
JUDGE = re.search(r'JUDGE = """(.*?)"""', open(f"{HERE}/reactions_v2.py").read(), re.S).group(1)
S = json.load(open(f"{SP}/persona/hist_sample.json")); C2 = json.load(open(f"{SP}/react_v2/cache_v2.json")); C0 = json.load(open(f"{SP}/react_site/cache_site.json")); CARDS = json.load(open(f"{SP}/harness_cards/hybrid_v3_k24.json"))
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); AC = pd.read_parquet(f"{OUT}/all_comments.parquet"); nt = AC[~AC.team]; cnt = nt.groupby("launch_id").size()
li = dict(zip(L.id, L.i)); day = dict(zip(L.id, L.day))
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str)
J_ = lambda t: json.loads(t) if isinstance(t, str) and t.startswith("[") else []
team = {i: {str(x).lower() for x in J_(m) if x} | ({str(p).lower()} if isinstance(p, str) and p else set()) for i, m, p in zip(W.id, W.makers, W.poster)}
pool = [x for x in S if str(x["id"]) in li and cnt.get(str(x["id"]), 0) >= 8 and C0.get(f"truth|{x['slug']}") and C2.get(f"gen|HYBRID_V3_K24|{x['slug']}") and C2.get(f"gen|BEST|{x['slug']}") and (CARDS.get(x["slug"]) or {}).get("personas")]
test = [pool[i] for i in rng.choice(len(pool), min(NL, len(pool)), replace=False)]; print("pool", len(pool), "test", len(test), flush=True)
cl = [l for l in L.id if cnt.get(l, 0) >= 3]; XC = X[[li[l] for l in cl]]; dcl = np.array([day[l] for l in cl])
SCH = 'Return JSON only: {"reactions": [{"reaction": "<1-2 sentences>", "concern": "<one specific concern or objection>", "question": "<one question for the makers>"}, ... exactly 24]}'
def g(prompt, mt):
    try: return json.loads(llm.gemini_call(prompt, mt))
    except Exception: return None
def one(x):
    lid, s = str(x["id"]), x["slug"]; i = li[lid]; D = day[lid]; r = L.iloc[i]; tm = team.get(lid, set())
    ok = (dcl < D) & np.array([not (team.get(l, set()) & tm) for l in cl]); sim = XC[ok] @ X[i]; cand = [c for c, o in zip(cl, ok) if o]; nb = [cand[j] for j in np.argsort(-sim)[:12]]
    rc = nt[nt.launch_id.isin(set(nb))].groupby("launch_id").head(4)
    real = "\n".join(f"- on {L.name[li[a]]} ({L.tagline[li[a]]}): \"{t[:240]}\"" for a, t in zip(rc.launch_id, rc.text))
    RB = "\n\nREAL COMMENTS THAT USERS LEFT ON SIMILAR EARLIER LAUNCHES (evidence of what this audience actually says; carry a point over only if it applies to this product):\n" + real
    topics = ", ".join(json.loads(x["topics"])) if isinstance(x["topics"], str) and x["topics"].startswith("[") else ""; desc = (r["description"] or "")[:1200]
    P_ = CARDS[s]["personas"][:24]
    p3 = pm.PROMPT.format(name=r["name"], tagline=r["tagline"] or "", desc=desc, topics=topics, groups="\n".join(pm.gtxt(k, c) for k, c in enumerate(P_))) + RB
    p1 = ("You forecast the comments a product will receive on its Product Hunt launch day. Write 24 distinct comments in a short Product Hunt voice, covering the range of what real commenters will say. "
          "Be specific to THIS product; do not praise generically.\n\nLAUNCH\nName: " + str(r["name"]) + "\nTagline: " + str(r["tagline"]) + "\nDescription: " + desc + "\nTopics: " + topics + RB + "\n\n" + SCH)
    pf = ("You forecast the comments a product will receive on its Product Hunt launch day. Write 24 distinct comments in a short Product Hunt voice.\n"
          "Rules: (1) every comment must name a specific feature, claim or detail taken from THIS launch's own text below; (2) use the real comments from similar launches as evidence of what this audience asks, "
          "and carry a point over ONLY if it applies to something this launch actually says it does; (3) no generic praise, no points about things this launch does not mention, no repeats of the same point.\n\n"
          "LAUNCH\nName: " + str(r["name"]) + "\nTagline: " + str(r["tagline"]) + "\nDescription: " + desc + "\nTopics: " + topics + RB + "\n\n" + SCH)
    fmt = lambda a: [f"{y.get('reaction', '')} Concern: {y.get('concern', '')} Question: {y.get('question', '')}" for y in ((a or {}).get("reactions") or []) if isinstance(y, dict)][:24]
    a1, af = fmt(g(p1, 7000)), fmt(g(pf, 7000)); pan = C2[f"gen|HYBRID_V3_K24|{s}"]; best = C2[f"gen|BEST|{s}"]
    arms = {"REAL24": a1, "PANEL": pan, "FOCUSED": af}
    if not all(len(v) >= 4 for v in arms.values()): return None
    th = C0[f"truth|{s}"]; own = nt[nt.launch_id == lid].text.tolist()[:30]
    pts = (g("Real comments on a Product Hunt launch (makers' replies excluded). List the distinct concerns or questions commenters raised (max 10; skip pure praise). JSON only: {\"points\": [\"...\"]}\n\n" + "\n".join("- " + t[:380] for t in own), 1500) or {}).get("points", [])[:10]
    if len(pts) < 2 or len(th) < 2: return None
    res = {"slug": s, "focused_comments": af, "n_themes": len(th), "n_points": len(pts), "sizes": {a: len(v) for a, v in arms.items()}}
    for a, c in arms.items():
        B = "\n".join(f"{k + 1}. {t}" for k, t in enumerate(c))
        j1 = g(JUDGE.format(a="\n".join(f"{k + 1}. {t['theme']}" for k, t in enumerate(th)), b=B), 900)
        j2 = g("Two lists about the same product. REAL: specific concerns or questions real commenters raised. CANDIDATE: forecast comments. A candidate matches a real point only if it raises the same substance (not merely the same topic). "
               "JSON only: {\"real_matched\": [true|false per REAL point, in order], \"candidate_matched\": [true|false per CANDIDATE, in order]}\n\nREAL:\n" + "\n".join(f"{k + 1}. {t}" for k, t in enumerate(pts)) + "\n\nCANDIDATE:\n" + B, 900)
        try:
            ac, bp = j1["a_covered"], j1["b_present"]; rm, cm = j2["real_matched"], j2["candidate_matched"]
            if len(ac) != len(th) or len(rm) != len(pts): return None
            _r, _p = float(np.mean([bool(v) for v in ac])), float(np.mean([bool(v) for v in bp[:len(c)]]))
            res[a] = {"theme_f1": (2 * _p * _r / (_p + _r) if _p + _r else 0.0), "theme_recall": float(np.mean([bool(v) for v in ac])), "theme_precision": float(np.mean([bool(v) for v in bp[:len(c)]])), "strict_recall": float(np.mean([bool(v) for v in rm])), "strict_precision": float(np.mean([bool(v) for v in cm[:len(c)]]))}
        except Exception: return None
    return res
with cf.ThreadPoolExecutor(6) as ex: R = [r for r in ex.map(one, test) if r]
ARMS = ["REAL24", "PANEL", "FOCUSED"]; MET = ["theme_recall", "strict_recall", "theme_precision", "strict_precision", "theme_f1"]
T = pd.DataFrame([{f"{a}|{m}": r[a][m] for a in ARMS for m in MET} for r in R])
def ci(v): b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]; return [round(float(100 * v.mean()), 1), round(float(100 * np.percentile(b, 2.5)), 1), round(float(100 * np.percentile(b, 97.5)), 1)]
PAIRS = [("FOCUSED", "PANEL"), ("FOCUSED", "REAL24"), ("PANEL", "REAL24")]
out = {"launches": len(T), "pool": len(pool), "themes": int(sum(r["n_themes"] for r in R)), "strict_points": int(sum(r["n_points"] for r in R)), "median_outputs_per_arm": {a: float(np.median([r["sizes"][a] for r in R])) for a in ARMS},
       "arms": {a: {m: ci(T[f"{a}|{m}"].values) for m in MET} for a in ARMS}, "paired": {f"{a} minus {b}": {m: ci((T[f"{a}|{m}"] - T[f"{b}|{m}"]).values) for m in MET} for a, b in PAIRS},
       "usd": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3)}
pr = out["paired"]; lb = lambda k, m: pr[k][m][1]; ub = lambda k, m: pr[k][m][2]
out["readings"] = {"theme F1 >= panel (point)": bool(pr["FOCUSED minus PANEL"]["theme_f1"][0] >= 0), "theme F1 clearly better (lower bound > 0)": bool(lb("FOCUSED minus PANEL", "theme_f1") > 0),
                   "strict recall not worse": bool(ub("FOCUSED minus PANEL", "strict_recall") >= 0)}
out["FOCUSED replaces the panel (pre-registered)"] = out["readings"]["theme F1 >= panel (point)"] and out["readings"]["strict recall not worse"]
json.dump({**out, "per_launch": R}, open(f"{OUT}/focused_full.json", "w"), indent=1)
json.dump(out, open(f"{OUT}/focused.json", "w"), indent=1); print(json.dumps(out, indent=1))
