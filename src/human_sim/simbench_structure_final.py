"""Consolidated routed method on equal data (no model calls) + clean ablations, vs the best individual method per shape.

sharp side   : agreement-sharpened blend (simbench_structure_sharp2), fitted on dev sharp questions
shallow side : temper(blend of {twoway, seg, sibraw, d3dyn}, t), fitted on dev shallow questions
router       : P(top answer >= 70%), cross-fitted on dev; final = pi*sharp + (1-pi)*shallow
Ablations keep the router and the other side fixed and refit only the side that changes."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_v2method as V2
from human_sim.simbench_routing_audit import ci
from human_sim.simbench_structure_routed2 import T_SHALLOW, attach, blend, fit_side, logit, router
from human_sim.simbench_structure_seg import load
from human_sim.simbench_structure_sharp2 import MEM, add_model_members, fit, sharp_pred

SHALLOW = ["twoway", "seg", "sibraw", "d3dyn"]


def main():
    x = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")
    dev, ev = load("dev", "D3dyn"), load("eval", "D3dyn")
    for qs, w in ((dev, "dev"), (ev, "eval")):
        attach(qs, x)
        add_model_members(qs, w)
    pd_, pe = router(dev, ev)
    dsh, dlo = [q for q in dev if q["top_share"] >= 0.7], [q for q in dev if q["top_share"] < 0.7]
    sides = {"sharp: full": (MEM, None), "sharp: no decomposition (no twoway, no fa)": ([m for m in MEM if m not in ("twoway", "fa")], None)}
    th = {k: fit(dsh, v[0]) for k, v in sides.items()}
    lo = {"shallow: full": fit_side(dlo, SHALLOW, T_SHALLOW),
          "shallow: no clustering (no seg)": fit_side(dlo, [m for m in SHALLOW if m != "seg"], T_SHALLOW),
          "shallow: no two-way decomposition": fit_side(dlo, [m for m in SHALLOW if m != "twoway"], T_SHALLOW),
          "shallow: raw only (sibraw + d3dyn)": fit_side(dlo, ["sibraw", "d3dyn"], T_SHALLOW)}
    for k, v in lo.items():
        print(f"{k:40s} weights {({a: round(b, 1) for a, b in v[0].items() if b > 0})} temp {v[1]}")

    def combo(qs, p, sk, lk, ab):
        pi = 1 / (1 + np.exp(-(ab[0] * logit(p) + ab[1])))
        return {q["qid"]: w * sharp_pred(q, th[sk], sides[sk][0]) + (1 - w) * blend(q, *lo[lk]) for q, w in zip(qs, pi)}

    grid = [(a, b) for a in (0.5, 1.0, 2.0, 4.0) for b in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    ab = max(grid, key=lambda g: np.mean([V2.S(q, v) for q, v in zip(dev, combo(dev, pd_, "sharp: full", "shallow: full", g).values())]))
    print("router", ab)
    variants = {"FINAL": ("sharp: full", "shallow: full")}
    variants.update({f"ablate {k}": (k, "shallow: full") for k in sides if k != "sharp: full"})
    variants.update({f"ablate {k}": ("sharp: full", k) for k in lo if k != "shallow: full"})
    P = {nm: combo(ev, pe, s, l, ab) for nm, (s, l) in variants.items()}
    pd.to_pickle(P["FINAL"], M.OUT / "structure_final_eval_preds.pkl")
    v4r = pd.read_pickle(M.OUT / "v4_refit_eval_preds.pkl")
    B = pd.read_pickle(M.OUT / "structure_decomp_eval_preds.pkl")["B  D3dyn + raw extracted data"]
    rep = {}
    for sl, sel in (("SHARP", lambda q: q["top_share"] >= 0.7), ("SHALLOW", lambda q: q["top_share"] < 0.7),
                    ("  moderate", lambda q: 0.5 <= q["top_share"] < 0.7), ("  no majority", lambda q: q["top_share"] < 0.5), ("ALL", lambda q: True)):
        qs = [q for q in ev if sel(q) and q["qid"] in v4r]
        f = np.array([V2.S(q, P["FINAL"][q["qid"]]) for q in qs])
        comp = {"v4 refit (same data)": v4r, "B raw blend (same data)": B}
        comp.update({k: P[k] for k in variants if k != "FINAL"})
        print(f"\n== {sl}: N {len(qs)}  FINAL {f.mean():.1f}")
        rep[sl] = {"N": len(qs), "FINAL": float(f.mean())}
        for k, pr in comp.items():
            s = np.array([V2.S(q, pr[q["qid"]]) for q in qs])
            print(f"   vs {k:48s} {s.mean():5.1f}  FINAL - it {(f - s).mean():+5.1f} {ci(f - s)}")
            rep[sl][k] = {"S": float(s.mean()), "diff": float((f - s).mean()), "ci": ci(f - s)}
    (M.OUT / "structure_final_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
