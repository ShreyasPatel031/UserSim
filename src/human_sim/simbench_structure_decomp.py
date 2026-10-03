"""What do dimension reduction and clustering add ON TOP of the extracted data? (no model calls)

Every variant gets the same data under the overlap rule (no answer to the target question from any group that may
contain the target's respondents). Base B = D3dyn + the raw extracted same-question answers, no structure:
  sibraw = size-weighted mean answer of disjoint same-country groups (e.g. other age bands)
  ocraw  = mean answer of the same demographic group in other countries
Then B + one structural layer at a time:
  +offset     sibling contrast (siblings shifted by the target's offset from them on similar questions)
  +clustering cross-national/sibling opinion segments (soft mixture)
  +dimred     factor completion (factor analysis on groups x questions)
Each variant: simplex weights over its members + one temperature, fitted on dev, scored once on eval."""

from __future__ import annotations

import itertools
import json
import sys

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_v2method as V2
from human_sim.simbench_routing_audit import ci
from human_sim.simbench_structure_seg import load

TOOLS = {"sibraw": ("sib:0@sib", 19, 0), "ocraw": ("mean", 19, 0), "offset": ("sib@sib", 19, 0),
         "clustering": ("segsoft@sib", 19, 8), "dimred": ("fa@sib", 10, 2)}
VARIANTS = {"A  D3dyn alone": ["d3dyn"],
            "B  D3dyn + raw extracted data": ["d3dyn", "sibraw", "ocraw"],
            "C  B + offset (contrast)": ["d3dyn", "sibraw", "ocraw", "offset"],
            "D  B + clustering": ["d3dyn", "sibraw", "ocraw", "clustering"],
            "E  B + dimension reduction": ["d3dyn", "sibraw", "ocraw", "dimred"],
            "F  B + clustering + dimension reduction": ["d3dyn", "sibraw", "ocraw", "clustering", "dimred"]}
STEP = 0.1
TEMPS = (0.9, 1.0, 1.15, 1.3)


def temper(p, t):
    r = np.power(np.clip(p, 1e-9, None), t)
    return r / r.sum()


def attach(qs, x):
    for q in qs:
        q["m"] = {"d3dyn": q["d3dyn"]}
        for k, cfg in TOOLS.items():
            v = x.get(cfg, {}).get(q["qid"])
            if v is not None:
                q["m"][k] = np.asarray(v)


def blend(q, w, t):
    use = [(wi, q["m"][k]) for k, wi in w.items() if wi > 0 and k in q["m"]]
    return temper(sum(wi * v for wi, v in use) / sum(wi for wi, _ in use), t) if use else temper(q["d3dyn"], t)


def fit(dev, keys):
    k10 = int(round(1 / STEP))
    grid = [dict(zip(keys, np.array(c) / k10)) for c in itertools.product(range(k10 + 1), repeat=len(keys)) if sum(c) == k10]
    return max(((w, t) for w in grid for t in TEMPS), key=lambda wt: np.mean([V2.S(q, blend(q, *wt)) for q in dev]))


def main():
    x = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")
    dev, ev = load("dev", "D3dyn"), load("eval", "D3dyn")
    attach(dev, x)
    attach(ev, x)
    fits, preds = {}, {}
    for nm, keys in VARIANTS.items():
        fits[nm] = fit(dev, keys)
        preds[nm] = {q["qid"]: blend(q, *fits[nm]) for q in ev}
        print(f"{nm:42s} weights {({k: round(v, 1) for k, v in fits[nm][0].items() if v > 0})} temp {fits[nm][1]}", flush=True)
    pd.to_pickle(preds, M.OUT / "structure_decomp_eval_preds.pkl")
    sys.argv = ["x"]
    from human_sim import simbench_panel_offsets as V  # noqa: E402
    v4 = {q["qid"]: V.predict(q, V.th, V.mu, V.sd) for q in V.ev}
    shape = lambda q: "sharp" if q["top_share"] >= 0.7 else ("moderate" if q["top_share"] >= 0.5 else "no majority")  # noqa: E731
    rep = {"fits": {k: {"weights": v[0], "temp": v[1]} for k, v in fits.items()}, "slices": {}}
    B = "B  D3dyn + raw extracted data"
    for sl, sel in (("sharp", lambda q: shape(q) == "sharp"), ("moderate", lambda q: shape(q) == "moderate"),
                    ("no majority", lambda q: shape(q) == "no majority"), ("ALL", lambda q: True)):
        qs = [q for q in ev if sel(q)]
        print(f"\n== {sl} (eval N {len(qs)})")
        sb = np.array([V2.S(q, preds[B][q["qid"]]) for q in qs])
        rep["slices"][sl] = {}
        for nm in VARIANTS:
            s = np.array([V2.S(q, preds[nm][q["qid"]]) for q in qs])
            line = f"   {nm:42s} {s.mean():5.1f}"
            if nm != B:
                line += f"   vs B {(s - sb).mean():+5.1f} {ci(s - sb)}"
            rep["slices"][sl][nm] = {"S": float(s.mean()), "vs_B": [float((s - sb).mean()), ci(s - sb)]}
            print(line)
        q4 = [q for q in qs if q["qid"] in v4]
        print(f"   (v4 original, on its {len(q4)}: {np.mean([V2.S(q, v4[q['qid']]) for q in q4]):.1f}; B on same: {np.mean([V2.S(q, preds[B][q['qid']]) for q in q4]):.1f})")
    (M.OUT / "structure_decomp_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
