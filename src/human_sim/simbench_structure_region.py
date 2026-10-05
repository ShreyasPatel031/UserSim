"""Other-country answers for questions without the two-way decomposition (no model calls).

For a target (survey, country C, group g, question q): answers to q from OTHER countries only (overlap rule):
  same group g in other countries (Grouped rows) and other countries' population totals (Pop rows).
Variants: plain mean; region-weighted mean (countries in C's world region count more; region = a fixed, hand-coded
map, interpretable and needing no shared questions); diagnostic oracle = best single other country (uses the truth)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim import simbench_structure_xnat as XN

REGION = {
    # Afrobarometer
    **{c: "West Africa" for c in ["Benin", "Burkina Faso", "Cabo Verde", "Côte d'Ivoire", "Gambia", "Ghana", "Guinea", "Liberia", "Mali", "Mauritania", "Niger", "Nigeria", "Senegal", "Sierra Leone", "Togo"]},
    **{c: "East Africa" for c in ["Ethiopia", "Kenya", "Madagascar", "Mauritius", "Seychelles", "Sudan", "Tanzania", "Uganda"]},
    **{c: "Southern Africa" for c in ["Angola", "Botswana", "Eswatini", "Lesotho", "Malawi", "Mozambique", "Namibia", "South Africa", "Zambia", "Zimbabwe"]},
    **{c: "Central Africa" for c in ["Cameroon", "Congo-Brazzaville", "Gabon", "São Tomé and Príncipe"]},
    **{c: "North Africa" for c in ["Morocco", "Tunisia"]},
    # Europe
    **{c: "Nordic" for c in ["Denmark", "Finland", "Iceland", "Norway", "Sweden"]},
    **{c: "Western Europe" for c in ["Austria", "Belgium", "France", "Germany", "Ireland", "the Netherlands", "Netherlands", "Switzerland", "the United Kingdom", "Great Britain"]},
    **{c: "Southern Europe" for c in ["Cyprus", "Greece", "Italy", "Portugal", "Spain", "Israel"]},
    **{c: "Eastern Europe" for c in ["Bulgaria", "Croatia", "Czechia", "Czech Republic", "Estonia", "Hungary", "Latvia", "Lithuania", "Montenegro", "North Macedonia", "Poland", "Russia", "Serbia", "Slovakia", "Slovenia", "Georgia"]},
    # Americas
    **{c: "Central America & Caribbean" for c in ["Costa Rica", "Dominican Republic", "El Salvador", "Guatemala", "Honduras", "Mexico", "Panama"]},
    **{c: "Andean" for c in ["Bolivia", "Colombia", "Ecuador", "Peru", "Venezuela"]},
    **{c: "Southern Cone" for c in ["Argentina", "Brazil", "Chile", "Paraguay", "Uruguay", "Suriname"]},
    **{c: "Anglo" for c in ["Australia", "New Zealand", "United States"]},
    **{c: "Asia" for c in ["China", "India", "Japan", "Philippines", "South Korea", "Taiwan", "Thailand", "Turkey"]},
}


def other_country_answers(sv, svp, t):
    """[(country, answer vector in the target's option order)] from other countries: same group, else population total."""
    st, C = t["stem"], t["country"]
    ds = t["q"]["dataset"]
    out = {}
    if st in sv[ds]["keys"] and t["split"] != "Pop" and len(t["cell"][2]) == 1:
        (a, v), = t["cell"][2]
        keys = sv[ds]["keys"][st]
        for c in sv[ds]["cells"]:
            if c[1] != C and len(c[2]) == 1 and c[2][0][0] == a and XN.values_overlap(c[2][0][1], v) and (c, st) in sv[ds]["obs"]:
                out.setdefault(c[1], []).append(sv[ds]["obs"][(c, st)][[keys.index(k) for k in t["q"]["keys"]]] if set(keys) == set(t["q"]["keys"]) else None)
    if not out and st in svp[ds]["keys"]:
        keys = svp[ds]["keys"][st]
        for c in svp[ds]["cells"]:
            if c[1] != C and not c[2] and (c, st) in svp[ds]["obs"] and set(keys) == set(t["q"]["keys"]):
                out.setdefault(c[1], []).append(svp[ds]["obs"][(c, st)][[keys.index(k) for k in t["q"]["keys"]]])
    return [(c, np.mean([x for x in v if x is not None], axis=0)) for c, v in out.items() if any(x is not None for x in v)]


def main():
    held = L.held_rows()
    sv, svp = L.build_surveys(held), L.build_surveys(held, split="Pop")
    res = {}
    for w in ("dev", "eval"):
        for t in L.targets(w):
            res[t["q"]["qid"]] = {"country": t["country"], "region": REGION.get(t["country"]), "others": other_country_answers(sv, svp, t)}
    pd.to_pickle(res, M.OUT / "structure_othercountry.pkl")
    miss = sorted({c for r in res.values() for c, _ in r["others"] if c not in REGION})
    print("countries without a region:", miss)
    print("targets with other-country answers:", sum(bool(r["others"]) for r in res.values()), "of", len(res))


if __name__ == "__main__":
    main()
