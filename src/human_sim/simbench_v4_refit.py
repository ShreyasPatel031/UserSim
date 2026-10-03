"""v4 persona offsets refitted with the same newly allowed data (no model calls).

Same functional form as v4 (gated mixture of bases, learned sharpening, demographic persona offsets), with two extra
bases: sibraw (disjoint same-country groups' answer to the question) and ocraw (same group in other countries), each
falling back to retr6_rev2 when missing. Fitted on v4's dev questions, scored on its eval questions."""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.argv = ["x"]
from human_sim import simbench_mass_levers as M  # noqa: E402
from human_sim import simbench_panel_offsets as V  # noqa: E402  (fits the original v4)
from human_sim import simbench_structure_v2method as V2  # noqa: E402
from human_sim.simbench_routing_audit import ci  # noqa: E402

x = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")
EXTRA = {"sibraw": ("sib:0@sib", 19, 0), "ocraw": ("mean", 19, 0)}


def main():
    orig = {q["qid"]: V.predict(q, V.th, V.mu, V.sd) for q in V.ev}
    for q in V.dev + V.ev:
        for k, cfg in EXTRA.items():
            v = x[cfg].get(q["qid"])
            q["preds"][k] = np.asarray(v) if v is not None else np.asarray(q["preds"]["plain (retr6_rev2)"])
    V.BASES = V.BASES + list(EXTRA)
    k = len(V.mu) + 1
    n = (len(V.BASES) + 1) * k

    def loss(th):
        return -np.mean([V.fastS(q, V.predict(q, th, V.mu, V.sd)) for q in V.dev]) + 0.05 * float(np.sum(th ** 2))

    r = minimize(loss, np.zeros(n), method="Powell", options={"maxiter": 3000})
    r = minimize(loss, r.x, method="Powell", options={"maxiter": 3000})
    new = {q["qid"]: V.predict(q, r.x, V.mu, V.sd) for q in V.ev}
    pd.to_pickle(new, M.OUT / "v4_refit_eval_preds.pkl")
    dec = pd.read_pickle(M.OUT / "structure_decomp_eval_preds.pkl")
    shape = lambda q: "sharp" if sorted(q["h"])[-1] >= 0.7 else ("moderate" if q["h"].max() >= 0.5 else "no majority")  # noqa: E731
    out = {}
    for nm, sel in (("sharp", lambda q: shape(q) == "sharp"), ("moderate", lambda q: shape(q) == "moderate"),
                    ("no majority", lambda q: shape(q) == "no majority"), ("ALL", lambda q: True)):
        qs = [q for q in V.ev if sel(q)]
        s_new = np.array([V2.S(q, new[q["qid"]]) for q in qs]); s_old = np.array([V2.S(q, orig[q["qid"]]) for q in qs])
        line = f"{nm:12s} N {len(qs):3d} | v4 original {s_old.mean():.1f} | v4 refit with new data {s_new.mean():.1f} ({(s_new - s_old).mean():+.1f})"
        for vn in ("B  D3dyn + raw extracted data", "C  B + offset (contrast)", "D  B + clustering", "E  B + dimension reduction"):
            s = np.array([V2.S(q, dec[vn][q["qid"]]) for q in qs])
            line += f" | {vn[:1]} {s.mean():.1f} (vs v4-refit {(s - s_new).mean():+.1f} {ci(s - s_new)})"
        print(line)
        out[nm] = {"v4_original": float(s_old.mean()), "v4_refit": float(s_new.mean())}
    (M.OUT / "v4_refit_report.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
