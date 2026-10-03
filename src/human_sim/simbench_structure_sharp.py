"""Sharp vs shallow: which statistical tool family fits which kind of question, and a method routed on it.

Sharp = concentrated answers (normalized entropy < 0.65), shallow = spread answers. The diagnostic split uses the real
answers (only to check the hypothesis); the method splits on the MODEL's predicted entropy (no real answers), with
the cutoff, tool and blend weight fitted on dev and scored once on eval against retr6_rev2.

Usage: python -m human_sim.simbench_structure_sharp [fit|report]"""

from __future__ import annotations

import ast
import json
import sys

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L

SHARP = 0.65
CACHE = M.OUT / "structure_sharp_toolpreds.pkl"
MODEL = "plain"
WS = np.linspace(0, 0.6, 13)
TAUS = (0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85)


def ci(d):
    d = np.asarray(d, float)
    if len(d) < 5:
        return (None, None)
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def candidates():
    """Per family, the best dev configs on sharp and on shallow questions (true split) and overall."""
    tun = pd.read_pickle(M.OUT / "structure_l3_tuning.pkl")
    devS = {ast.literal_eval(k): v for k, v in tun["devS"].items()}
    dev = L.targets("dev")
    sharp = np.array([t["q"]["Hn"] < SHARP for t in dev])
    out = set()
    for fam, tools in (("DR", L.DR_TOOLS), ("CL", L.CL_TOOLS)):
        cfgs = [c for c in devS if c[0] in tools]
        for mask in (sharp, ~sharp, np.ones_like(sharp)):
            common = mask & np.all([~np.isnan(devS[c]) for c in cfgs], axis=0)
            ranked = sorted(cfgs, key=lambda c: -devS[c][common].mean())
            out.update(ranked[:2])
    return sorted(out)


def fit():
    cfgs = candidates()
    print("candidate configs:", cfgs, flush=True)
    cache = pd.read_pickle(CACHE) if CACHE.exists() else {}
    F = L.Fitter(L.build_surveys(L.held_rows()))
    sets = {w: L.targets(w) for w in ("dev", "eval")}
    for cfg in cfgs:
        if cfg in cache:
            continue
        cache[cfg] = {t["q"]["qid"]: L.predict(F, t, *cfg) for w in sets for t in sets[w]}
        pd.to_pickle(cache, CACHE)
        F.cache.clear()
        print("cached", cfg, flush=True)


def report():
    cache = pd.read_pickle(CACHE)
    cfgs = list(cache)
    sets = {w: L.targets(w) for w in ("dev", "eval")}
    S = L.S
    fam_of = lambda c: "DR" if c[0] in L.DR_TOOLS else "CL"  # noqa: E731
    rep = {"configs": [list(c) for c in cfgs]}

    # 1) diagnostic: tool alone, true sharp vs shallow; config chosen on dev per (bucket, family), scored on eval
    diag = {}
    for b, sel in (("sharp", lambda t: t["q"]["Hn"] < SHARP), ("shallow", lambda t: t["q"]["Hn"] >= SHARP)):
        dv = [t for t in sets["dev"] if sel(t)]
        ev = [t for t in sets["eval"] if sel(t)]
        pick = {}
        for fam in ("DR", "CL"):
            fc = [c for c in cfgs if fam_of(c) == fam]
            common = [t for t in dv if all(cache[c][t["q"]["qid"]] is not None for c in fc)]
            pick[fam] = max(fc, key=lambda c: np.mean([S(t["q"], cache[c][t["q"]["qid"]]) for t in common]))
        both = [t for t in ev if all(cache[pick[f]][t["q"]["qid"]] is not None for f in pick) and MODEL in t["q"]["preds"]]
        sd = np.array([S(t["q"], cache[pick["DR"]][t["q"]["qid"]]) for t in both])
        sc = np.array([S(t["q"], cache[pick["CL"]][t["q"]["qid"]]) for t in both])
        sm = np.array([S(t["q"], t["q"]["preds"][MODEL]) for t in both])
        diag[b] = {"N_eval": len(both), "DR_config": list(pick["DR"]), "CL_config": list(pick["CL"]),
                   "DR_alone": float(sd.mean()), "CL_alone": float(sc.mean()), "CL_minus_DR": float((sc - sd).mean()),
                   "ci": ci(sc - sd), "model": float(sm.mean())}
        print(f"[diagnostic, real-answer split] {b:8s} eval N {len(both):3d}: component tool {sd.mean():5.1f} | clustering tool {sc.mean():5.1f} "
              f"| clustering - component {(sc - sd).mean():+.1f} {ci(sc - sd)} | model {sm.mean():.1f}")
    rep["diagnostic"] = diag

    # 2) method: split on the model's predicted entropy; per side pick config + blend weight on dev
    def blend_score(t, cfg, w):
        p = np.asarray(t["q"]["preds"][MODEL])
        tool = cache[cfg][t["q"]["qid"]]
        return S(t["q"], p if tool is None else w * tool + (1 - w) * p)

    dv = [t for t in sets["dev"] if MODEL in t["q"]["preds"]]
    best = None
    for tau in TAUS:
        choice, total = {}, 0.0
        for side in ("sharp", "shallow"):
            sub = [t for t in dv if (L.M.Hn(np.asarray(t["q"]["preds"][MODEL])) < tau) == (side == "sharp")]
            if not sub:
                choice[side] = (cfgs[0], 0.0)
                continue
            opts = [(c, w) for c in cfgs for w in WS]
            c, w = max(opts, key=lambda o: np.mean([blend_score(t, *o) for t in sub]))
            choice[side] = (c, float(w))
            total += sum(blend_score(t, c, w) for t in sub)
        if best is None or total > best[0]:
            best = (total, tau, choice)
    _, tau, choice = best
    ev = [t for t in sets["eval"] if MODEL in t["q"]["preds"]]
    side_of = lambda t: "sharp" if L.M.Hn(np.asarray(t["q"]["preds"][MODEL])) < tau else "shallow"  # noqa: E731
    base = np.array([S(t["q"], t["q"]["preds"][MODEL]) for t in ev])
    fin = np.array([blend_score(t, *choice[side_of(t)]) for t in ev])
    d = fin - base
    meth = {"tau_model_entropy": tau, "choice": {k: {"config": list(v[0]), "family": fam_of(v[0]), "weight": v[1]} for k, v in choice.items()},
            "N": len(ev), "model": float(base.mean()), "method": float(fin.mean()), "diff": float(d.mean()), "ci": ci(d), "slices": {}}
    for name, m in [("true sharp", [t["q"]["Hn"] < SHARP for t in ev]), ("true shallow", [t["q"]["Hn"] >= SHARP for t in ev]),
                    ("true divided", [t["q"]["Hn"] >= M.DIV for t in ev]), ("Grouped", [t["split"] == "Grouped" for t in ev]),
                    ("Pop", [t["split"] == "Pop" for t in ev])]:
        m = np.array(m, bool)
        meth["slices"][name] = {"N": int(m.sum()), "diff": float(d[m].mean()), "ci": ci(d[m])}
    rep["method"] = meth
    print(f"\n[method, no real answers] split on model entropy < {tau}: sharp side -> {fam_of(choice['sharp'][0])} {choice['sharp'][0]} w={choice['sharp'][1]:.2f}; "
          f"shallow side -> {fam_of(choice['shallow'][0])} {choice['shallow'][0]} w={choice['shallow'][1]:.2f}")
    print(f"   eval N {len(ev)}: retr6_rev2 {base.mean():.1f} -> method {fin.mean():.1f} ({d.mean():+.1f} {ci(d)})")
    print("   " + " | ".join(f"{k} N{v['N']} {v['diff']:+.1f} {v['ci']}" for k, v in meth["slices"].items()))
    (M.OUT / "structure_sharp_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    {"fit": fit, "report": report}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
