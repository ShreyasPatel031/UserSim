"""Build the cross-national segment block for the D3dynseg prompt (no model calls).

For every dev/eval/full shared-survey target: the segment estimate (best segmentation tool, with the similar-question
proxy when the exact question has no cross-national answers) and, when the exact question is covered, the 3 closest
other-country groups by name with their real answers. Target country never contributes.
Output: structure_segprompt.pkl {(dataset, persona, template): {"seg": {key: share}, "exact": bool, "near": [(label, {key: share})]}}"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim import simbench_structure_xnat as XN

OUT = M.OUT / "structure_segprompt.pkl"
TOOL = ("segsoft", 19, 8)


def nearest(sv, t, k=3, K=19):
    st = t["stem"]
    if st not in sv["keys"]:
        return []
    nb = L.neighbours(sv, t["text"], st, K)
    X, rows, cols = L.local_matrix(sv, [s for s, _ in nb], (st,))
    sl = cols[st]
    same = np.array([c[1] == t["country"] for c in rows])
    tgt = [i for i, c in enumerate(rows) if (c == t["cell"] if t["split"] != "Pop" else (c[1] == t["country"] and c[2]))]
    others = [i for i in range(len(rows)) if not same[i] and not np.isnan(X[i, sl.start])]
    if not tgt or not others:
        return []
    nb_sl = [c for c in cols.values() if c != sl]
    ds_ = []
    for i in others:
        d = [np.mean([0.5 * np.abs(X[ti, c] - X[i, c]).sum() for ti in tgt if not np.isnan(X[ti, c.start])] or [np.nan])
             for c in nb_sl if not np.isnan(X[i, c.start])]
        d = [x for x in d if not np.isnan(x)]
        if len(d) >= 2:
            ds_.append((float(np.mean(d)), i))
    ds_.sort()
    keys = sv["keys"][st]
    return [(sv["label"].get(rows[i], str(rows[i])), {k: float(X[i, sl][keys.index(k)]) for k in t["q"]["keys"]}) for _, i in ds_[:k]]


def main():
    tool = TOOL
    for a in sys.argv:
        if a.startswith("--tool="):
            name, K, r = a.split("=")[1].split(",")
            tool = (name, int(K), int(r))
    sv = L.build_surveys(L.held_rows())
    out = pd.read_pickle(OUT) if OUT.exists() else {}
    for w in ("dev", "eval"):
        sample, _, _ = A.build_env(25, 100, 7, w)
        n = 0
        for t in L.targets(w):
            s = sv[t["q"]["dataset"]]
            name = tool[0]
            p, why = XN.complete_px(s, t, name, tool[1], tool[2]) if not name.endswith("+px") else XN.complete_px(s, t, name[:-3], tool[1], tool[2])
            if p is None:
                continue
            r = sample.loc[t["q"]["i"]]
            key = (r.dataset_name, A._filled_persona(r), r.input_template)
            out[key] = {"seg": dict(zip(t["q"]["keys"], map(float, p))), "exact": why == "ok",
                        "near": nearest(s, t) if why == "ok" else []}
            n += 1
        print(w, "segment blocks", n, flush=True)
    pd.to_pickle(out, OUT)


if __name__ == "__main__":
    main()
