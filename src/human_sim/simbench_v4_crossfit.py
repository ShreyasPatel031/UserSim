"""Out-of-fold v4 persona-offset predictions on dev (5 folds) + full-dev-fit predictions on eval.

Needed so a downstream ensemble can use v4 as a member without fitting its weights on v4's in-sample dev predictions.
Output: v4_crossfit_preds.pkl {qid: prediction}."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.model_selection import KFold

from human_sim import simbench_mass_levers as M
from human_sim import simbench_panel_offsets as V  # fits v4 on all dev at import

OUT = M.OUT / "v4_crossfit_preds.pkl"


def main():
    out = {q["qid"]: V.predict(q, V.th, V.mu, V.sd) for q in V.ev}
    dev = V.dev
    for k, (tr, te) in enumerate(KFold(5, shuffle=True, random_state=0).split(dev)):
        sub = [dev[i] for i in tr]

        def loss(th):
            return -np.mean([V.fastS(q, V.predict(q, th, V.mu, V.sd)) for q in sub]) + 0.05 * float(np.sum(th ** 2))

        r = minimize(loss, np.zeros(V.n), method="Powell", options={"maxiter": 3000})
        r = minimize(loss, r.x, method="Powell", options={"maxiter": 3000})
        for i in te:
            out[dev[i]["qid"]] = V.predict(dev[i], r.x, V.mu, V.sd)
        print("fold", k, "done", flush=True)
    pd.to_pickle(out, OUT)


if __name__ == "__main__":
    main()
