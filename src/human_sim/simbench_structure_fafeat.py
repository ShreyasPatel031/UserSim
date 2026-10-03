"""Factor-analysis concentration profile per target question (no model calls, no target answers).

For each dev/eval shared-survey question: fit factor analysis (K=10 neighbour questions by text, 3 factors) on the
subgroup-cell x option matrix of the NEIGHBOUR questions only (the target question is never in the matrix; eval/dev
rows never enter any matrix). From the fit, summarise how concentrated answers in this part of the survey are for the
target's group: fitted top-answer share, share of neighbours with a >=70% top answer, between-group spread, how much of
the variance the first factor carries, and how well the factors explain the target group's rows.
Output: structure_fafeat.pkl {qid: {feature: value}}."""

from __future__ import annotations

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L

OUT = M.OUT / "structure_fafeat.pkl"
K, R = 10, 3


def profile(F, t):
    ds = t["q"]["dataset"]
    f = F.get(ds, t["text"], t["stem"], K, "fa", R)
    if f is None:
        return None
    if t["split"] == "Pop":
        rows = [i for c, i in f["ridx"].items() if c[1] == t["country"]]
    else:
        rows = [f["ridx"][t["cell"]]] if t["cell"] in f["ridx"] else []
    own = bool(rows)
    if not rows:
        rows = list(range(len(f["rows"])))
    X, fit = f["X"], f["fit"]
    w_tot, fit_top, obs_top, cons, between, resid = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    for st, sim in f["nb"]:
        sl = f["cols"][st]
        w = max(sim, 0.01)
        Fs = np.clip(fit[:, sl], 1e-6, None)
        Fs = Fs / Fs.sum(1, keepdims=True)
        Xs = X[:, sl]
        top_rows = Fs[rows].max(1)
        ft = float(top_rows.mean())
        ok = ~np.isnan(Xs[rows, 0])
        ot = float(np.nanmax(Xs[rows][ok], axis=1).mean()) if ok.any() else ft
        rs = float(np.abs(Xs[rows][ok] - Fs[rows][ok]).sum(1).mean() / 2) if ok.any() else 0.0
        between += w * float(Fs.std(0).sum() / 2)
        fit_top += w * ft
        obs_top += w * ot
        cons += w * float(ft >= 0.7)
        resid += w * rs
        w_tot += w
    Ximp = np.where(np.isnan(X), fit, X)
    Z = Ximp - Ximp.mean(0)
    s = np.linalg.svd(Z, compute_uv=False) if min(Z.shape) > 1 else np.array([1.0])
    ev = s ** 2 / max(float((s ** 2).sum()), 1e-12)
    return {"fa_fit_top": fit_top / w_tot, "fa_obs_top": obs_top / w_tot, "fa_cons_frac": cons / w_tot,
            "fa_between": between / w_tot, "fa_resid": resid / w_tot, "fa_ev1": float(ev[0]),
            "fa_ev3": float(ev[:3].sum()), "fa_own_rows": float(own), "fa_nb_sim": float(np.mean([s_ for _, s_ in f["nb"]]))}


def main():
    F = L.Fitter(L.build_surveys(L.held_rows()))
    out = {}
    for w in ("dev", "eval"):
        for i, t in enumerate(L.targets(w)):
            out[t["q"]["qid"]] = profile(F, t)
            if len(F.cache) > 200:
                F.cache.clear()
        print(w, "done", sum(v is not None for v in out.values()), flush=True)
    pd.to_pickle(out, OUT)


if __name__ == "__main__":
    main()
