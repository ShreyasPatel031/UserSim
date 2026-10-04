"""Sharp side with agreement-driven sharpening (no model calls).

Members (same data as v4 refit): d3dyn, plain retr6_rev2, retr6, sibraw, ocraw, twoway (two-way decomposition), fa.
Blend weights = softmax(theta_w) over available members. Exponent = exp(b0 + b1*agree + b2*Hn(blend) + b3*max(blend)),
agree = share of available members whose top option equals the blend's top option. All fitted on dev questions with
top answer >= 70% (Powell, L2). Scored on eval truly-sharp questions (perfect routing) and plugged into the routed method."""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_v2method as V2
from human_sim.simbench_routing_audit import ci
from human_sim.simbench_structure_routed2 import attach, blend, logit, router, temper
from human_sim.simbench_structure_seg import load

MEM = ["d3dyn", "plain", "retr6", "sibraw", "ocraw", "twoway", "fa"]


def add_model_members(qs, which):
    M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU), "retr6": ("retr6", M.HAIKU)}
    pr = {q["qid"]: q["preds"] for q in M.load(which)}
    for q in qs:
        for k in ("plain", "retr6"):
            if k in pr.get(q["qid"], {}):
                q["m"][k] = np.asarray(pr[q["qid"]][k])


def sharp_pred(q, th, mem=MEM):
    w = np.exp(th[:len(mem)] - th[:len(mem)].max())
    use = [(wi, q["m"][k]) for wi, k in zip(w, mem) if k in q["m"]]
    mix = sum(wi * v for wi, v in use) / sum(wi for wi, _ in use)
    top = int(np.argmax(mix))
    agree = np.mean([int(np.argmax(v)) == top for _, v in use])
    b = th[len(mem):]
    t = np.exp(np.clip(b[0] + b[1] * agree + b[2] * M.Hn(mix) + b[3] * mix.max(), -1.0, 1.5))
    return temper(mix, t)


def fit(qs, mem=MEM):
    def loss(th):
        return -np.mean([V2.S(q, sharp_pred(q, th, mem)) for q in qs]) + 0.05 * float(np.sum(th ** 2))

    th0 = np.zeros(len(mem) + 4)
    th0[len(mem)] = 0.5
    r = minimize(loss, th0, method="Powell", options={"maxiter": 20000, "xtol": 1e-3, "ftol": 1e-4})
    return r.x


def main():
    x = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")
    dev, ev = load("dev", "D3dyn"), load("eval", "D3dyn")
    for qs, w in ((dev, "dev"), (ev, "eval")):
        attach(qs, x)
        add_model_members(qs, w)
    dsh = [q for q in dev if q["top_share"] >= 0.7]
    v4r = pd.read_pickle(M.OUT / "v4_refit_eval_preds.pkl")
    esh = [q for q in ev if q["top_share"] >= 0.7 and q["qid"] in v4r]
    v = np.array([V2.S(q, v4r[q["qid"]]) for q in esh])
    out = {}
    for nm, mem in (("sharp side (agreement sharpening, all members)", MEM),
                    ("  without two-way decomposition & fa", [m for m in MEM if m not in ("twoway", "fa")]),
                    ("  without fa", [m for m in MEM if m != "fa"])):
        th = fit(dsh, mem)
        s = np.array([V2.S(q, sharp_pred(q, th, mem)) for q in esh])
        w = np.exp(th[:len(mem)] - th[:len(mem)].max()); w /= w.sum()
        print(f"{nm:52s} eval sharp (perfect routing) {s.mean():.1f} vs v4-refit {v.mean():.1f}: {(s - v).mean():+.1f} {ci(s - v)} | weights {dict(zip(mem, w.round(2)))} | sharpen {th[len(mem):].round(2)}", flush=True)
        out[nm] = {"theta": th.tolist(), "mem": mem, "eval_sharp": float(s.mean()), "vs_v4refit": [float((s - v).mean()), ci(s - v)]}
    (M.OUT / "structure_sharp2_report.json").write_text(json.dumps(out, indent=2))
    pd.to_pickle(out, M.OUT / "structure_sharp2_fits.pkl")


if __name__ == "__main__":
    main()
