"""Layer 2b: variance-explaining retrieval (contrasting groups, component coverage) vs similar-question retrieval.

Paired on the questions both arms cover. Bands and shape labels use the real answers only to slice the scoring."""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M

NEW = ("G1_contrast_rev2", "G2_contrast_rev2", "K2_cover_rev2", "K3_cover_rev2", "KC1_rev2", "KC2_rev2")
BASE = ("retr6_rev2", "D3_same_group_same_topic")


def ci(d):
    d = np.asarray(d, float)
    if len(d) < 5:
        return (None, None)
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def band(q):
    return "consensus" if q["Hn"] < 0.65 else ("mixed" if q["Hn"] < M.DIV else "divided")


def main(which="dev"):
    arms = {a: (a, M.HAIKU) for a in NEW + BASE}
    M.EVAL_ARMS = M.DEV_ARMS = arms
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl").set_index("qid")
    qs = M.load(which)
    S = lambda q, a: 100 * (1 - M.tvd(q["preds"][a], q["h"]) / q["norm"])  # noqa: E731
    out = {}
    for new in NEW:
        out[new] = {}
        for base in BASE:
            qq = [q for q in qs if new in q["preds"] and base in q["preds"]]
            if len(qq) < 10:
                continue
            d = np.array([S(q, new) - S(q, base) for q in qq])
            row = {"N": len(qq), "new": float(np.mean([S(q, new) for q in qq])), "base": float(np.mean([S(q, base) for q in qq])),
                   "diff": float(d.mean()), "ci": ci(d), "slices": {}}
            slices = {f"band={b}": [band(q) == b for q in qq] for b in ("consensus", "mixed", "divided")}
            slices.update({f"shape={s}": [l1.loc[q["qid"], "label"] == s for q in qq]
                           for s in ("unimodal-wide", "multimodal", "binary/3-option", "categorical")})
            slices.update({f"split={s}": [q["split"] == s for q in qq] for s in ("Pop", "Grouped")})
            for name, m in slices.items():
                m = np.array(m)
                if m.sum() >= 5:
                    row["slices"][name] = {"N": int(m.sum()), "diff": float(d[m].mean()), "ci": ci(d[m])}
            out[new][base] = row
            print(f"\n{new} vs {base}: N {len(qq)}  {row['new']:.1f} vs {row['base']:.1f}  {row['diff']:+.1f} {row['ci']}")
            print("   " + " | ".join(f"{k} N{v['N']} {v['diff']:+.1f} {v['ci']}" for k, v in row["slices"].items()))
    path = M.OUT / "structure_l2b_report.json"
    allres = json.loads(path.read_text()) if path.exists() else {}
    allres[which] = out
    path.write_text(json.dumps(allres, indent=2, default=float))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dev")
