"""PRODUCT-USE-1 scorer for one day (run after the close, after truth_daily has D's ranks; PREREG addendum 11).
  python score.py D SP [--rehearsal]      (SP = work dir; forward_says' comment download + frozen consensus truth are reused)
Residual: capture of the real top 3 / 5 when the structural top N is re-ordered by each arm's score, minus the structural order; within-day
Spearman of the score with (real rank - structural rank). Arms: sim (product use: would-use x preference), stageb (rerank_frozen yes_share),
homepage (control would_use). Product reaction: forward_says.judge (recall / precision / complaint recall) against the frozen consensus truth,
for sim (non-artefact problems + likes + comparison reasons) and the homepage control. Writes results/calibration/D/product_use/score.json.
"""
import json, os, re, subprocess, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); SIMLAB = os.path.join(HERE, "..")
D, SP = [a for a in sys.argv[1:] if not a.startswith("--")][:2]; REH = "--rehearsal" in sys.argv
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; PUB = f"{B}/{'_rehearsal/' if REH else ''}results/calibration/{D}/product_use"
gj = lambda p: json.loads(subprocess.run(["gsutil", "cat", p], capture_output=True).stdout or b"null")
LU, OUT, HP = gj(f"{PUB}/lineup.json"), gj(f"{PUB}/outputs.json"), gj(f"{PUB}/control_homepage.json")
TR = (gj(f"{B}/results/web/truth_daily.json") or {}).get("days", {}).get(D) or {}
ranks = {str(k): int(v) for k, v in (TR.get("ranks") or {}).items()}
if not ranks: sys.exit(f"no truth ranks for {D} yet")
SB = {str(x["id"]): x.get("yes_share") for x in (gj(f"{B}/results/calibration/{D}/rerank_frozen.json") or {}).get("launches", [])}
ids = [l["id"] for l in LU["launches"]]; srank = {l["id"]: l["structural_rank"] for l in LU["launches"]}
real = {i: ranks.get(i, 99) for i in ids}                               # unranked (not featured / not in the counted list) = bottom
arms = {"sim": {x["launch_id"]: x.get("sim_score") for x in (OUT or {}).get("launches", [])},
        "stageb": SB, "homepage": {x["launch_id"]: x.get("would_use") for x in (HP or {}).get("launches", [])}}
def reorder(sc):
    v = [sc.get(i) for i in ids]; med = np.nanmedian([x for x in v if x is not None]) if any(x is not None for x in v) else 0.0
    s = [(-(x if x is not None else med), srank[i]) for x, i in zip(v, ids)]          # ties / missing keep structural order
    return [ids[k] for k in sorted(range(len(ids)), key=lambda k: s[k])]
truth_top = lambda k: set(sorted(ids, key=lambda i: real[i])[:k])
def cap(order, k): return len(set(order[:k]) & truth_top(k)) / k
struct = sorted(ids, key=lambda i: srank[i]); RES = {"structural": {f"top{k}": cap(struct, k) for k in (3, 5)}}
for a, sc in arms.items():
    if not any(sc.get(i) is not None for i in ids): RES[a] = {"available": False}; continue
    o = reorder(sc); miss = [real[i] - srank[i] for i in ids]; v = [sc.get(i) for i in ids]; ok = [k for k, x in enumerate(v) if x is not None]
    rho = spearmanr([v[k] for k in ok], [miss[k] for k in ok]).correlation if len(ok) >= 5 else None
    RES[a] = {"available": True, **{f"top{k}": cap(o, k) for k in (3, 5)}, **{f"top{k}_minus_structural": cap(o, k) - cap(struct, k) for k in (3, 5)},
              "spearman_vs_miss": None if rho is None or np.isnan(rho) else float(rho), "n_scored": len(ok)}

# ---- product reaction (forward_says' comment pull, consensus truth and judge; truth shared through the bucket) ----
os.makedirs(os.path.join(SIMLAB, "reports", "forward_sim", "truth"), exist_ok=True)
subprocess.run(f"gsutil -m -q cp '{B}/results/calibration/forward_says/truth/truth_{D}.v*.json' {os.path.join(SIMLAB, 'reports', 'forward_sim', 'truth')}/ 2>/dev/null", shell=True)
src = open(os.path.join(SIMLAB, "forward_says.py")).read(); src = src[:src.index("def one(lid):")]
G = {"__name__": "fs", "__file__": os.path.join(SIMLAB, "forward_says.py")}; argv0 = sys.argv; sys.argv = ["forward_says.py", D, SP]
exec(compile(src, "forward_says_prefix", "exec"), G); sys.argv = argv0
F = pd.DataFrame((OUT or {}).get("findings", []))
def sim_cands(i):
    if F.empty: return []
    g = F[(F.launch_id == i) & (F.slot == "launch") & (F.artefact == "none")]
    c = [p for ps in g.problems for p in (ps or [])] + [p for ps in g.likes for p in (ps or [])]
    seen, out = set(), []
    for x in c:
        k = re.sub(r"\W+", " ", x.lower()).strip()
        if k and k not in seen: seen.add(k); out.append(x)
    return out[:14]
hp = {x["launch_id"]: (x.get("complaints") or []) + (x.get("praise") or []) + (x.get("comparisons") or []) for x in (HP or {}).get("launches", [])}
REACT = []
for i in ids:
    cm = G["NT"][G["NT"].post == i].sort_values("created").text.tolist()
    if len(cm) < 5: continue                                              # forward_says' rule: at least 5 non-team comments
    tr = G["truth_for"](i, "\n".join(f"- {t[:400]}" for t in cm[:40])); th, ct = (tr or {}).get("themes") or [], (tr or {}).get("complaints") or []
    for a, cand in (("sim", sim_cands(i)), ("homepage", hp.get(i) or [])):
        if cand: REACT.append({"launch_id": i, "arm": a, "n_cand": len(cand), **G["judge"](th, ct, cand)})
_tv = sorted(int(re.search(r"\.v(\d+)\.json$", p).group(1)) for p in __import__("glob").glob(os.path.join(G["TDIR"], f"truth_{D}.v*.json")))
if G["NEW_TRUTH"] or (_tv and any(l not in json.load(open(os.path.join(G["TDIR"], f"truth_{D}.v{_tv[-1]}.json")))["launches"] for l in G["TRUTHS"])):
    k = (_tv[-1] + 1) if _tv else 1; p = os.path.join(G["TDIR"], f"truth_{D}.v{k}.json")
    json.dump({"day": D, "version": k, "rule": "themes present in >= 2 of 3 independent extractions (Gemini merge)", "launches": G["TRUTHS"]}, open(p, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/calibration/forward_says/truth/"])
RD = pd.DataFrame(REACT)
react = {a: {m: (float(g[m].mean()) if m in g and g[m].notna().any() else None) for m in ("recall", "precision", "complaint_recall")} | {"n_launches": int(len(g))}
         for a, g in RD.groupby("arm")} if len(RD) else {}
S = {"day": D, "rehearsal": REH, "scored_at": pd.Timestamp.now(tz="UTC").isoformat(), "truth_source": "results/web/truth_daily.json",
     "residual": RES, "reaction": react, "reaction_rows": REACT, "n_launches": len(ids),
     "n_sessions_excluded_access": (OUT or {}).get("n_sessions_excluded_access"), "n_launches_no_prediction": (OUT or {}).get("n_launches_no_prediction"),
     "clean_session_rate": (OUT or {}).get("clean_session_rate"),
     "artefact_rate_launch_sessions": (float((F[F.slot == "launch"].artefact != "none").mean()) if len(F) else None)}
p = os.path.join(SP, f"pu_score_{D}.json"); json.dump(S, open(p, "w"), indent=1, default=str); subprocess.run(["gsutil", "-q", "cp", p, f"{PUB}/score.json"])
print(json.dumps({k: S[k] for k in ("day", "residual", "reaction", "artefact_rate_launch_sessions")}, default=str)[:1500])
