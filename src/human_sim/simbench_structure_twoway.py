"""Two-way decomposition (country effect + group effect) on the target question, no model calls.

For a subgroup target (country C, attribute a = v), question q:
  country level   L_C   = size-weighted mean answer to q of C's disjoint groups (same attribute, other values)
  group gap       G     = mean over other countries C' of [ answer_{C', a=v}(q) - L_{C'} ], where L_{C'} uses the same
                          sibling values as in C (so the gap compares like with like)
  prediction            = L_C + lam * G     (clipped, renormalised)
Variants: "dd"  all other countries equally;
          "ddc" gaps weighted by how similar C' is to C (countries clustered by their population answers on other
                questions; k nearest countries) - clustering of countries.
No answer to q from any group that may contain the target's respondents is used (overlap rule). Pop targets: none.
Output: adds ("dd", lam, 0) and ("ddc", lam, k) entries to structure_xnat_preds.pkl."""

from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np
import pandas as pd

from human_sim import simbench_structure_l3 as L
from human_sim import simbench_structure_xnat as XN

LAMS = (0.5, 1.0)
KS = (5, 10)


def country_profiles(sv):
    """country -> {stem: mean answer over its subgroup cells} from the Grouped training rows (any attribute)."""
    acc = defaultdict(lambda: defaultdict(list))
    for (c, st), v in sv["obs"].items():
        acc[c[1]][st].append(v)
    return {C: {st: np.mean(vs, axis=0) for st, vs in d.items()} for C, d in acc.items()}


def country_dist(prof, a, b, skip):
    common = [st for st in prof[a] if st in prof[b] and st != skip and len(prof[a][st]) == len(prof[b][st])]
    if len(common) < 5:
        return None
    return float(np.mean([0.5 * np.abs(prof[a][st] - prof[b][st]).sum() for st in common]))


def predict(sv, prof, t, lam, k=None):
    if t["split"] == "Pop" or t["stem"] not in sv["keys"] or len(t["cell"][2]) != 1:
        return None
    st, (ds, C, ((a, v),)) = t["stem"], t["cell"]
    w = lambda c: max(sv["size"].get(c, 1.0) or 1.0, 1.0)  # noqa: E731
    by_country = defaultdict(dict)  # country -> value -> answer to q
    for c in sv["cells"]:
        if len(c[2]) == 1 and c[2][0][0] == a and (c, st) in sv["obs"]:
            by_country[c[1]][c[2][0][1]] = (sv["obs"][(c, st)], w(c))
    sib_vals = [val for val in by_country.get(C, {}) if not XN.values_overlap(val, v)]
    if not sib_vals:
        return None
    Lc = sum(by_country[C][s][0] * by_country[C][s][1] for s in sib_vals) / sum(by_country[C][s][1] for s in sib_vals)
    gaps = []
    for C2, vals in by_country.items():
        if C2 == C:
            continue
        own = [val for val in vals if XN.values_overlap(val, v)]
        sibs = [s for s in sib_vals if s in vals]
        if len(own) != 1 or not sibs:
            continue
        L2 = sum(vals[s][0] * vals[s][1] for s in sibs) / sum(vals[s][1] for s in sibs)
        gaps.append((C2, vals[own[0]][0] - L2))
    G = np.zeros_like(Lc)
    if gaps:
        if k is None:
            G = np.mean([g for _, g in gaps], axis=0)
        else:
            dd = [(country_dist(prof, C, C2, st), g) for C2, g in gaps]
            dd = sorted([x for x in dd if x[0] is not None], key=lambda x: x[0])[:k]
            if dd:
                tau = np.median([d for d, _ in dd]) + 1e-6
                ws = np.array([np.exp(-d / tau) for d, _ in dd])
                G = sum(wi * g for wi, (_, g) in zip(ws, dd)) / ws.sum()
            else:
                G = np.mean([g for _, g in gaps], axis=0)
    p = np.clip(Lc + lam * G, 1e-4, None)
    keys = sv["keys"][st]
    if set(keys) != set(t["q"]["keys"]):
        return None
    p = p[[keys.index(x) for x in t["q"]["keys"]]]
    return p / p.sum()


def main():
    held = L.held_rows()
    sv, svp = L.build_surveys(held), L.build_surveys(held, split="Pop")
    profs = {ds: country_profiles(s) for ds, s in sv.items()}
    nd = [country_dist(profs["ESS"], "Germany", c2, None) for c2 in list(profs["ESS"])[:6]]
    print("sanity: ESS distances from Germany", [None if d is None else round(d, 3) for d in nd], flush=True)
    out = pd.read_pickle(XN.OUT)
    sets = {w: L.targets(w) for w in ("dev", "eval")}
    for lam in (1.0,):
        for k in KS + (3,):
            cfg = ("dd", lam, 0) if k is None else ("ddc", lam, k)
            res = {}
            for w in sets:
                for t in sets[w]:
                    ds = t["q"]["dataset"]
                    res[t["q"]["qid"]] = predict(sv[ds], profs[ds], t, lam, k)
            out[cfg] = res
            for w in sets:
                ok = [t for t in sets[w] if res[t["q"]["qid"]] is not None]
                print(f"{str(cfg):18s} {w}: coverage {len(ok)}/{len(sets[w])} S {np.mean([L.S(t['q'], res[t['q']['qid']]) for t in ok]):.1f}", flush=True)
            pd.to_pickle(out, XN.OUT)


if __name__ == "__main__":
    main()
