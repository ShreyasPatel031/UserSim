"""Ceiling with every non-overlapping population allowed (no model calls).

Rule: no answer to the target question from any group that may contain the target's respondents (the target group in
any wave, overlapping same-country groups, the country total for a subgroup target, any same-country group for a
country target). Everything else is allowed: other countries and disjoint same-country groups (e.g. other age bands).

Members: D3dyn (base), sibling contrast, segments, factor completion and nearest groups computed under that rule.
Blend = simplex weights over available members + one temperature, fitted on dev, scored once on eval by shape vs
D3dyn and v4. Also an oracle (best member per question, diagnostic only) as the upper bound of this member set."""

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

TOOLS = {"sib": ("sib@sib", 19, 0), "seg": ("segsoft@sib", 19, 8), "fa": ("fa@sib", 10, 2), "knn": ("knn@sib", 19, 10)}
STEP = 0.1


def temper(p, t):
    r = np.power(np.clip(p, 1e-9, None), t)
    return r / r.sum()


def members(qs, x):
    for q in qs:
        q["m"] = {"d3dyn": q["d3dyn"]}
        for k, cfg in TOOLS.items():
            v = x.get(cfg, {}).get(q["qid"])
            if v is not None:
                q["m"][k] = np.asarray(v)


def blend(q, w, t):
    use = [(wi, q["m"][k]) for k, wi in w.items() if wi > 0 and k in q["m"]]
    if not use:
        return temper(q["d3dyn"], t)
    return temper(sum(wi * v for wi, v in use) / sum(wi for wi, _ in use), t)


def main():
    x = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")
    dev, ev = load("dev", "D3dyn"), load("eval", "D3dyn")
    members(dev, x)
    members(ev, x)
    keys = ["d3dyn"] + list(TOOLS)
    for k in TOOLS:
        print(f"coverage {k}: dev {np.mean([k in q['m'] for q in dev]):.0%} eval {np.mean([k in q['m'] for q in ev]):.0%}")
    k10 = int(round(1 / STEP))
    grid = [dict(zip(keys, np.array(c) / k10)) for c in itertools.product(range(k10 + 1), repeat=len(keys)) if sum(c) == k10 and c[0] > 0]
    best = max(((w, t) for w in grid for t in (0.9, 1.0, 1.15, 1.3)), key=lambda wt: np.mean([V2.S(q, blend(q, *wt)) for q in dev]))
    print("fitted on dev:", {k: v for k, v in best[0].items() if v > 0}, "temperature", best[1])
    sys.argv = ["x"]
    from human_sim import simbench_panel_offsets as V  # noqa: E402
    v4 = {q["qid"]: V.predict(q, V.th, V.mu, V.sd) for q in V.ev}
    shape = lambda q: "sharp" if q["top_share"] >= 0.7 else ("moderate" if q["top_share"] >= 0.5 else "no majority")  # noqa: E731
    rep = {"weights": best[0], "temperature": best[1], "slices": {}}
    for nm, sel, only in [(s, (lambda s: lambda q: shape(q) == s)(s), o) for s in ("sharp", "moderate", "no majority") for o in (False, True)] + \
                         [("shallow", lambda q: q["top_share"] < 0.7, True), ("all", lambda q: True, False), ("all", lambda q: True, True)]:
        qs = [q for q in ev if sel(q) and (not only or q["qid"] in v4)]
        o = np.array([V2.S(q, blend(q, *best)) for q in qs])
        d = np.array([V2.S(q, q["d3dyn"]) for q in qs])
        orc = np.array([max(V2.S(q, v) for v in q["m"].values()) for q in qs])
        tag = f"{nm} [{'411 with v4' if only else '625'}]"
        line = f"{tag:24s} N {len(qs):3d} ceiling-method {o.mean():.1f} | vs D3dyn {(o - d).mean():+.1f} {ci(o - d)}"
        r = {"N": len(qs), "S": float(o.mean()), "vs_D3dyn": [float((o - d).mean()), ci(o - d)], "oracle": float(orc.mean())}
        if only:
            b = np.array([V2.S(q, v4[q["qid"]]) for q in qs])
            line += f" | vs v4 {(o - b).mean():+.1f} {ci(o - b)}"
            r["vs_v4"] = [float((o - b).mean()), ci(o - b)]
        line += f" | oracle best-member {orc.mean():.1f}"
        print(line)
        rep["slices"][tag] = r
    pd.to_pickle({q["qid"]: blend(q, *best) for q in ev}, M.OUT / "structure_ceiling_eval_preds.pkl")
    (M.OUT / "structure_ceiling_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
