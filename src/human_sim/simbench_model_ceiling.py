"""Eval: which parts of the divided-question error does a bigger model remove, and which remain?"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M

SON = "claude-sonnet-5-5"
ARMS = {
    "haiku": ("retr6_rev2", M.HAIKU),
    "haiku_panel": ("P_groundall5", M.HAIKU),
    "haiku_seg": ("B_n3_soft_rev2", M.HAIKU),
    "son": ("retr6_rev2", SON),
    "son_ground": ("B_ground3_rev2", SON),
}
SLICES = {
    "consensus+mixed (truth)": lambda q: q["Hn"] < M.DIV,
    "divided (truth)": lambda q: q["Hn"] >= M.DIV,
    "divided shared": lambda q: q["Hn"] >= M.DIV and q["group3"] == "shared_survey",
    "divided tasks": lambda q: q["Hn"] >= M.DIV and q["group3"] == "pop_only_task",
    "divided other pop": lambda q: q["Hn"] >= M.DIV and q["group3"] == "other_pop_only",
    "predicted divided": lambda q: not math.isnan(q["nbr_h"]) and q["nbr_h"] >= M.DIV,
    "all": lambda q: True,
}


def ci(d, n=2000):
    d = np.asarray(d, float)
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(n)])
    return round(float(b[int(.025 * n)]), 1), round(float(b[int(.975 * n) - 1]), 1)


def main():
    M.EVAL_ARMS = ARMS
    qs = M.load("eval")
    need = list(ARMS)
    out = {"gain_by_slice": {}, "components": {}, "by_dominant": {}}

    print("== Sonnet vs Haiku retr6_rev2, paired ΔS (eval)")
    print(f"{'slice':26s}{'N':>5s}{'Haiku':>7s}{'Son':>7s}{'ΔS':>7s}{'CI':>14s}{'Son+ground ΔS vs Son':>24s}")
    for n, pick in SLICES.items():
        qq = [q for q in qs if pick(q) and all(a in q["preds"] for a in need)]
        S = {a: np.array([M.components(q, q["preds"][a])["S"] for q in qq]) for a in need}
        d = S["son"] - S["haiku"]
        dg = S["son_ground"] - S["son"]
        out["gain_by_slice"][n] = {"N": len(qq), "haiku": float(S["haiku"].mean()), "son": float(S["son"].mean()),
                                   "delta": float(d.mean()), "ci": ci(d), "ground_vs_son": float(dg.mean()), "ground_ci": ci(dg),
                                   **{a: float(S[a].mean()) for a in need}}
        print(f"{n:26s}{len(qq):5d}{S['haiku'].mean():7.1f}{S['son'].mean():7.1f}{d.mean():+7.1f}{str(ci(d)):>14s}"
              f"{dg.mean():+10.1f} {str(ci(dg)):>13s}")

    df = M.part1([q for q in qs if all(a in q["preds"] for a in need)], arms=tuple(need))
    df = df[df.arm.isin(need)]
    print("\n== Remaining error by part, divided questions (absolute TVD, Shapley), eval")
    for gname, sel in {"divided shared": df.group3 == "shared_survey", "divided tasks": df.group3 == "pop_only_task",
                       "divided other pop": df.group3 == "other_pop_only"}.items():
        d = df[sel]
        rows = {}
        for a in need:
            x = d[d.arm == a]
            rest = x.TVD - x[["phi_location", "phi_assignment", "phi_profile"]].sum(axis=1)
            rows[a] = {"N": len(x), "TVD": x.TVD.mean(), "location": x.phi_location.mean(), "order": x.phi_assignment.mean(),
                       "shape": x.phi_profile.mean(), "rest": rest.mean(), "top1": x.top_right.mean(),
                       "flip": x.flip.mean(), "entropy_gap": x.entropy_gap.mean(), "spearman": x.spearman.mean()}
        out["components"][gname] = rows
        t = pd.DataFrame(rows).T
        print(f"\n-- {gname}")
        print(t.round(3).to_string())
        h, s = rows["haiku"], rows["son"]
        print("   Sonnet removes (share of Haiku's part): " + ", ".join(
            f"{k} {100 * (h[k] - s[k]) / h[k]:+.0f}%" for k in ("TVD", "location", "order", "shape")))

    print("\n== ΔS (Sonnet − Haiku) by Haiku's dominant error component, divided questions")
    dom = df[df.arm == "haiku"].set_index("qid").dominant
    ss = {a: df[df.arm == a].set_index("qid").S for a in ("haiku", "son", "son_ground")}
    for comp in ["order", "shape", "peaks", "location"]:
        ids = dom[dom == comp].index
        ids = [i for i in ids if i in ss["son"].index]
        if not ids:
            continue
        d = (ss["son"].loc[ids] - ss["haiku"].loc[ids]).values
        g = (ss["son_ground"].loc[ids] - ss["son"].loc[ids]).values
        out["by_dominant"][comp] = {"N": len(ids), "delta": float(d.mean()), "ci": ci(d), "ground_vs_son": float(g.mean()), "ground_ci": ci(g)}
        print(f"{comp:10s} N {len(ids):3d}  Son−Haiku {d.mean():+6.1f} {ci(d)}   ground−Son {g.mean():+6.1f} {ci(g)}")

    (M.OUT / "model_ceiling_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
