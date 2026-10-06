"""Two-way decomposition for COUNTRY-TOTAL questions (no model calls).

Target: country C's population answer to question q (no same-country subgroup may be used: they all overlap C).
  question level  Q  = mean over other countries C' of their population answer to q (Pop rows)
  country offset  G  = similarity-weighted mean over related questions q' (same option count, answered by C and by
                       other countries) of [ C's answer to q' - mean of other countries' answers to q' ]
  prediction         = Q + lam * G   (clipped, renormalised)
Variants: lam in {0 (question level only), 0.5, 1}; offset by option position. Scored on dev/eval country-total
questions in the 5 shared surveys, vs plain and D3dyn on the same questions."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim.simbench_structure_sharp import ci

K = 30


def predict(svp, t, lam):
    s = svp.get(t["q"]["dataset"])
    if s is None or t["stem"] not in s["keys"]:
        return None, "question not asked to any country at population level"
    C, st = t["country"], t["stem"]
    keys = s["keys"][st]
    if set(keys) != set(t["q"]["keys"]):
        return None, "keys differ"
    oth = [s["obs"][(c, st)] for c in s["cells"] if c[1] != C and not c[2] and (c, st) in s["obs"]]
    if not oth:
        return None, "no other country"
    Q = np.mean(oth, axis=0)
    cell = next((c for c in s["cells"] if c[1] == C and not c[2]), None)
    gaps = []
    if cell is not None:
        for st2, sim in L.neighbours(s, t["text"], st, K):
            own = s["obs"].get((cell, st2))
            if own is None or len(own) != len(Q):
                continue
            o2 = [s["obs"][(c, st2)] for c in s["cells"] if c[1] != C and not c[2] and (c, st2) in s["obs"]]
            if o2:
                gaps.append((max(sim, 0.01), own - np.mean(o2, axis=0)))
    G = sum(w * g for w, g in gaps) / sum(w for w, _ in gaps) if gaps else np.zeros_like(Q)
    p = np.clip(Q + lam * G, 1e-4, None)
    p = p[[keys.index(k) for k in t["q"]["keys"]]]
    return p / p.sum(), f"{len(oth)} other countries, {len(gaps)} related questions for the offset"


def predict_group(sv, t, lam, dd2):
    """Subgroup question with no disjoint same-country group: same group (same attribute value) in other countries
    on q + this group's offset from the same group abroad on related questions."""
    from human_sim import simbench_structure_xnat as XN
    if t["split"] == "Pop" or dd2.get(t["q"]["qid"]) is not None or len(t["cell"][2]) != 1:
        return None, "n/a"
    s = sv[t["q"]["dataset"]]
    st, C, ((a, v),) = t["stem"], t["cell"][1], t["cell"][2]
    if st not in s["keys"] or set(s["keys"][st]) != set(t["q"]["keys"]):
        return None, "question not in pool"
    keys = s["keys"][st]
    same_abroad = lambda st_: [s["obs"][(c, st_)] for c in s["cells"] if c[1] != C and len(c[2]) == 1 and c[2][0][0] == a and XN.values_overlap(c[2][0][1], v) and (c, st_) in s["obs"]]  # noqa: E731
    oth = same_abroad(st)
    if not oth:
        return None, "group not asked abroad"
    Q = np.mean(oth, axis=0)
    gaps = []
    for st2, sim in L.neighbours(s, t["text"], st, K):
        own = s["obs"].get((t["cell"], st2))
        if own is None or len(own) != len(Q):
            continue
        o2 = same_abroad(st2)
        if o2:
            gaps.append((max(sim, 0.01), own - np.mean(o2, axis=0)))
    G = sum(w * g for w, g in gaps) / sum(w for w, _ in gaps) if gaps else np.zeros_like(Q)
    p = np.clip(Q + lam * G, 1e-4, None)
    p = p[[keys.index(k) for k in t["q"]["keys"]]]
    return p / p.sum(), f"{len(oth)} countries, {len(gaps)} related questions"


def main():
    svp = L.build_surveys(L.held_rows(), split="Pop")
    S = lambda q, p: 100 * (1 - M.tvd(np.asarray(p), q["h"]) / q["norm"])  # noqa: E731
    out = {}
    for w in ("dev", "eval"):
        M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU), "d3dyn": ("D3dyn", M.HAIKU)}
        ts = [t for t in L.targets(w) if t["split"] == "Pop" and "plain" in t["q"]["preds"]]
        res = {lam: [predict(svp, t, lam) for t in ts] for lam in (0.0, 0.5, 1.0)}
        cov = [i for i, (p, _) in enumerate(res[1.0]) if p is not None]
        n_gap = sum(("0 related" not in res[1.0][i][1]) for i in cov)
        print(f"\n== {w}: country-total questions {len(ts)}; covered {len(cov)} (with a country offset {n_gap})")
        base = np.array([S(ts[i]["q"], ts[i]["q"]["preds"]["plain"]) for i in cov])
        line = f"   plain {base.mean():.1f}"
        d3 = [S(ts[i]["q"], ts[i]["q"]["preds"]["d3dyn"]) for i in cov if "d3dyn" in ts[i]["q"]["preds"]]
        if d3:
            line += f" | D3dyn {np.mean(d3):.1f} (n {len(d3)})"
        print(line)
        out[w] = {}
        for lam in (0.0, 0.5, 1.0):
            s = np.array([S(ts[i]["q"], res[lam][i][0]) for i in cov])
            m = (s + base) / 2  # 50/50 with plain, for reference
            mix = np.array([S(ts[i]["q"], 0.5 * np.asarray(res[lam][i][0]) + 0.5 * np.asarray(ts[i]["q"]["preds"]["plain"])) for i in cov])
            print(f"   lam {lam}: decomposition {s.mean():.1f} ({(s - base).mean():+.1f} {ci(s - base)}) | 50/50 with plain {mix.mean():.1f} ({(mix - base).mean():+.1f} {ci(mix - base)})")
            out[w][str(lam)] = {"N": len(cov), "decomp": float(s.mean()), "plain": float(base.mean()), "mix": float(mix.mean())}
    sv = L.build_surveys(L.held_rows())
    dd2 = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")[("dd2", 1.0, 0)]
    for w in ("dev", "eval"):
        M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU), "d3dyn": ("D3dyn", M.HAIKU)}
        ts = [t for t in L.targets(w) if t["split"] == "Grouped" and "plain" in t["q"]["preds"] and dd2.get(t["q"]["qid"]) is None]
        res = {lam: [predict_group(sv, t, lam, dd2) for t in ts] for lam in (0.0, 0.5, 1.0)}
        cov = [i for i, (p, _) in enumerate(res[1.0]) if p is not None]
        print(f"\n== {w} SUBGROUP questions without the decomposition: {len(ts)}; covered by same-group-abroad {len(cov)}")
        if not cov:
            continue
        base = np.array([S(ts[i]["q"], ts[i]["q"]["preds"]["plain"]) for i in cov])
        print(f"   plain {base.mean():.1f}")
        for lam in (0.0, 0.5, 1.0):
            sc = np.array([S(ts[i]["q"], res[lam][i][0]) for i in cov])
            mix = np.array([S(ts[i]["q"], 0.5 * np.asarray(res[lam][i][0]) + 0.5 * np.asarray(ts[i]["q"]["preds"]["plain"])) for i in cov])
            print(f"   lam {lam}: decomposition {sc.mean():.1f} ({(sc - base).mean():+.1f} {ci(sc - base)}) | 50/50 with plain {mix.mean():.1f} ({(mix - base).mean():+.1f} {ci(mix - base)})")
            out.setdefault(w + "_group", {})[str(lam)] = {"N": len(cov), "decomp": float(sc.mean()), "plain": float(base.mean()), "mix": float(mix.mean())}
    (M.OUT / "popdecomp_report.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
