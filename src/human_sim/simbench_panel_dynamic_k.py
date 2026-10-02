"""Demographic panel with a per-question number of personas.

Each demographic persona sees only its own group's real answers to similar questions. How much the groups differed on
those similar questions (never the target) decides how much weight goes to the demographic split versus a single
persona for the whole target population (its own retrieval). Cutoffs are tuned on dev and scored on eval."""

from __future__ import annotations

import ast
import json

import numpy as np

from human_sim import simbench_mass_levers as M
from human_sim import simbench_panel_criteria as C

SPLIT = "C7_split_own"


def split_info(q):
    segs = q["traces"][SPLIT]
    segs = ast.literal_eval(segs) if isinstance(segs, str) else segs
    return float(segs[0]["between_group_tvd"]), segs


def single(q):
    """One persona = the whole target population with its own retrieval."""
    return np.asarray(q["preds"]["C5_own"] if q["split"] == "Grouped" and "C5_own" in q["preds"] else q["preds"]["plain (retr6_rev2)"])


def fastS(q, p):
    return 100 * (1 - 0.5 * float(np.abs(np.asarray(p) - q["h"]).sum()) / q["norm"])


def hard(q, tau):
    v, _ = split_info(q)
    return np.asarray(q["preds"][SPLIT]) if v > tau else single(q)


def soft(q, tau, scale):
    v, _ = split_info(q)
    a = 1 / (1 + np.exp(-(v - tau) / scale))
    return a * np.asarray(q["preds"][SPLIT]) + (1 - a) * single(q)


def main():
    _, dev = C.scoreboard("dev", [SPLIT], also=("C5_own",))
    V = np.array([split_info(q)[0] for q in dev])
    taus = np.quantile(V, np.linspace(0, 1, 41))
    tau_h = max(taus, key=lambda t: np.mean([fastS(q, hard(q, t)) for q in dev]))
    grid = [(t, s) for t in taus for s in (0.005, 0.01, 0.02, 0.04, 0.08)]
    tau_s, sc = max(grid, key=lambda ts: np.mean([fastS(q, soft(q, *ts)) for q in dev]))
    print(f"dev-tuned: hard cutoff {tau_h:.3f} (split on {np.mean(V > tau_h):.0%} of dev questions); soft centre {tau_s:.3f} scale {sc}")
    res, ev = C.scoreboard("eval", [SPLIT], also=("C5_own",), extra={
        "v5 single persona only": single,
        "v5 hard: 1 persona or demographic split": lambda q: hard(q, tau_h),
        "v5 soft: population persona + demographic personas": lambda q: soft(q, tau_s, sc),
    })
    Ve = np.array([split_info(q)[0] for q in ev])
    bands = [C.band(q) for q in ev]
    print("\nshare of questions given the demographic split (hard rule), by true band:",
          {b: round(float(np.mean([v > tau_h for v, bb in zip(Ve, bands) if bb == b])), 2) for b in C.BANDS})
    div = [np.mean([M.tvd(np.array([s["dist"][k] for k in q["keys"]]), np.asarray(q["preds"][SPLIT])) for s in split_info(q)[1]]) for q in ev]
    print(f"how different demographic personas are with own-only retrieval (TVD to their average): {np.mean(div):.3f}")
    res["tuned"] = {"tau_hard": float(tau_h), "tau_soft": float(tau_s), "scale_soft": sc, "persona_diversity": float(np.mean(div))}
    (M.OUT / "panel_dynamic_k_report.json").write_text(json.dumps(res, indent=2, default=float))


if __name__ == "__main__":
    main()
