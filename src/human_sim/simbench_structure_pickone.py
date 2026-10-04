"""Pick-one method (no blends): per slice, a fixed priority order of sources; each question uses the FIRST source that
exists for it, tempered by one dev-fitted exponent. Every prediction comes from exactly one named source.

Sources (overlap rule applies to all): twoway (country level + group gap), sibraw (disjoint same-country groups),
seg (opinion segments), ocraw (same group in other countries), fa (factor completion), d3dyn (always exists).
Orders and exponents are chosen on dev only; eval scored once, compared with v4 refit (sharp) and raw blend B (shallow)."""

from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_v2method as V2
from human_sim.simbench_routing_audit import ci
from human_sim.simbench_structure_routed2 import attach, temper
from human_sim.simbench_structure_seg import load

SOURCES = ["twoway3", "twoway2", "d3dynseg", "sibraw", "ocraw"]
TEMPS = (0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5)


def pick(q, order):
    for k in order:
        if k in q["m"]:
            return k, q["m"][k]
    return "d3dyn", q["d3dyn"]


def per_source_temps(qs, order):
    """Each source's own exponent, fitted on the dev questions where that source is the one picked."""
    temps = {}
    for k in order + ["d3dyn"]:
        sub = [q for q in qs if pick(q, order)[0] == k]
        temps[k] = max(TEMPS, key=lambda t: np.mean([V2.S(q, temper(pick(q, order)[1], t)) for q in sub])) if sub else 1.0
    return temps


def predict(q, order, temps):
    k, v = pick(q, order)
    return temper(v, temps[k] if isinstance(temps, dict) else temps)


def score(qs, order, temps):
    return np.mean([V2.S(q, predict(q, order, temps)) for q in qs])


def best_order(dev):
    cands = [list(o) for r in range(0, 4) for o in itertools.permutations(SOURCES, r)]
    cands = [o for o in cands if not ("twoway3" in o and "twoway2" in o and o.index("twoway2") < o.index("twoway3"))]
    fits = [(o, per_source_temps(dev, o)) for o in cands]
    return max(fits, key=lambda ot: score(dev, *ot))


def main():
    x = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")
    dev, ev = load("dev", "D3dyn"), load("eval", "D3dyn")
    attach(dev, x)
    attach(ev, x)
    for qs, w in ((dev, "dev"), (ev, "eval")):  # the model shown same-group examples + cross-national segment answers
        M.EVAL_ARMS = M.DEV_ARMS = {"sg": ("D3dynseg", M.HAIKU)}
        sg = {q["qid"]: np.asarray(q["preds"]["sg"]) for q in M.load(w) if "sg" in q["preds"]}
        for q in qs:
            if q["qid"] in sg:
                q["m"]["d3dynseg"] = sg[q["qid"]]
    v4r = pd.read_pickle(M.OUT / "v4_refit_eval_preds.pkl")
    B = pd.read_pickle(M.OUT / "structure_decomp_eval_preds.pkl")["B  D3dyn + raw extracted data"]
    rep = {}
    for sl, sel, ref_name, ref in (("SHARP", lambda q: q["top_share"] >= 0.7, "v4 refit", v4r), ("SHALLOW", lambda q: q["top_share"] < 0.7, "raw blend B", B)):
        d, e = [q for q in dev if sel(q)], [q for q in ev if sel(q) and q["qid"] in v4r]
        print(f"\n===== {sl}: dev {len(d)}, eval {len(e)} (questions where v4 exists)")
        for k in SOURCES + ["d3dyn"]:
            o = [k] if k != "d3dyn" else []
            t = max(TEMPS, key=lambda t: score(d, o, t))
            print(f"   {k:8s} alone (else D3dyn), dev-best temp {t:<4}: dev {score(d, o, t):.1f}  eval {score(e, o, t):.1f}")
        o, t = best_order(d)
        s = np.array([V2.S(q, predict(q, o, t)) for q in e])
        r = np.array([V2.S(q, ref[q["qid"]]) for q in e])
        used = pd.Series([pick(q, o)[0] for q in e]).value_counts().to_dict()
        print(f"   BEST ORDER on dev: {' -> '.join(o + ['d3dyn'])}, temps {t}: dev {score(d, o, t):.1f} | eval {s.mean():.1f} vs {ref_name} {r.mean():.1f}: {(s - r).mean():+.1f} {ci(s - r)} | sources used on eval {used}")
        rep[sl] = {"order": o + ["d3dyn"], "temp": t, "eval": float(s.mean()), "ref": ref_name, "ref_S": float(r.mean()), "diff": float((s - r).mean()), "ci": ci(s - r), "used": used}
    (M.OUT / "structure_pickone_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
