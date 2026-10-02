"""Leak ceiling, with model: leak harness where same-question data exists, best non-leak setup elsewhere."""

from __future__ import annotations

import json
import sys
from collections import Counter

import numpy as np

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M

STRICT = "--strict" in sys.argv
ARMS = {"plain": ("retr6_rev2", M.HAIKU), "panel": ("P_groundall5", M.HAIKU),
        "leak": ("L_strict" if STRICT else "L_leak", M.HAIKU)}
ALLOWED = A._NO_OVERLAP if STRICT else None
if STRICT:
    ARMS["pers"] = ("P_strict5", M.HAIKU)


def data_estimate(row, keys):
    """Size-weighted mean of the closest relation's rows (no model)."""
    src = A._leak_sources(row, ALLOWED)
    if not src:
        return None, None
    rel = src[0][0]
    V, W = [], []
    for r, _, size, ans in src:
        if r != rel:
            continue
        v = np.array([float(ans.get(k, 0.0)) for k in keys])
        V.append(v / v.sum())
        W.append(size or 1.0)
    W = np.array(W)
    return rel, (W / W.sum()) @ np.array(V)


def prep(which):
    M.EVAL_ARMS = ARMS
    M.DEV_ARMS = ARMS
    sample, _, _ = A.build_env(25, 100, 7, which)
    qs = M.load(which)
    for q in qs:
        q["rel"], q["data"] = data_estimate(sample.loc[q["i"]], q["keys"])
    return qs


def S(q, p):
    return 100 * (1 - M.tvd(p, q["h"]) / q["norm"])


def ci(d):
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def nonleak(q):
    return (q["preds"]["plain"] + q["preds"]["panel"]) / 2 if "panel" in q["preds"] else q["preds"]["plain"]


def main():
    dev, ev = prep("dev"), prep("eval")
    # weight on the data-only estimate vs the leak harness, per relation, tuned on dev
    ws = np.linspace(0, 1, 21)
    wbest = {}
    for rel in {q["rel"] for q in dev if q["rel"]}:
        qq = [q for q in dev if q["rel"] == rel and "leak" in q["preds"]]
        if len(qq) >= 10:
            wbest[rel] = float(max(ws, key=lambda w: np.mean([S(q, w * q["data"] + (1 - w) * q["preds"]["leak"]) for q in qq])))
    print("dev-tuned weight on data-only estimate, per relation:", wbest)
    wpers = {}
    for rel in {q["rel"] for q in dev if q["rel"]}:
        qq = [q for q in dev if q["rel"] == rel and "pers" in q["preds"]]
        if len(qq) >= 10:
            wpers[rel] = float(max(ws, key=lambda w: np.mean([S(q, w * q["data"] + (1 - w) * q["preds"]["pers"]) for q in qq])))
    if wpers:
        print("dev-tuned weight on data-only estimate vs persona panel, per relation:", wpers)

    ev = [q for q in ev if "plain" in q["preds"]]
    pick = {
        "plain": lambda q: q["preds"]["plain"],
        "best non-leak (50/50 plain+panel)": nonleak,
        "data-only where available, else non-leak": lambda q: q["data"] if q["data"] is not None else nonleak(q),
        "leak harness where available, else non-leak": lambda q: q["preds"]["leak"] if "leak" in q["preds"] else nonleak(q),
        "leak harness + data blend (dev-tuned), else non-leak": lambda q: (
            wbest.get(q["rel"], 0) * q["data"] + (1 - wbest.get(q["rel"], 0)) * q["preds"]["leak"]
            if "leak" in q["preds"] and q["data"] is not None else nonleak(q)),
    }
    if wpers:
        pick["persona panel + evidence where available, else non-leak"] = (
            lambda q: q["preds"]["pers"] if "pers" in q["preds"] else nonleak(q))
        pick["persona panel + evidence + data blend (dev-tuned), else non-leak"] = lambda q: (
            wpers.get(q["rel"], 0) * q["data"] + (1 - wpers.get(q["rel"], 0)) * q["preds"]["pers"]
            if "pers" in q["preds"] and q["data"] is not None else nonleak(q))
    base = np.array([S(q, pick["plain"](q)) for q in ev])
    out = {"weights_pers": wpers, "weights": wbest, "overall": {}, "by_relation": {}, "by_dataset": {}}
    print(f"\n{'eval, all 981':55s}{'S':>6s}{'vs plain':>18s}")
    for nm, f in pick.items():
        s = np.array([S(q, f(q)) for q in ev])
        out["overall"][nm] = {"S": float(s.mean()), "vs_plain": float((s - base).mean()), "ci": ci(s - base)}
        print(f"{nm:55s}{s.mean():6.1f}{(s - base).mean():+7.1f} {str(ci(s - base)):>10s}")
    final = pick["leak harness + data blend (dev-tuned), else non-leak"]
    print(f"\n{'by closest relation':26s}{'N':>5s}{'plain':>7s}{'panel':>7s}{'data':>7s}{'leak':>7s}{'pers':>7s}{'final':>7s}")
    for rel in ["same_group_other_wave", "country_total", "same_country_subgroups", "disjoint_subgroup", "other_countries", None]:
        qq = [q for q in ev if q["rel"] == rel]
        if not qq:
            continue
        r = {"N": len(qq), "plain": np.mean([S(q, q["preds"]["plain"]) for q in qq]),
             "data": np.mean([S(q, q["data"]) for q in qq]) if rel else float("nan"),
             "leak": np.mean([S(q, q["preds"]["leak"]) for q in qq if "leak" in q["preds"]]) if rel else float("nan"),
             "panel": np.mean([S(q, q["preds"]["panel"]) for q in qq if "panel" in q["preds"]]),
             "pers": np.mean([S(q, q["preds"]["pers"]) for q in qq if "pers" in q["preds"]]) if rel and STRICT else float("nan"),
             "final": np.mean([S(q, final(q)) for q in qq])}
        out["by_relation"][str(rel)] = r
        print(f"{str(rel or 'no same-question data'):26s}{r['N']:5d}{r['plain']:7.1f}{r['panel']:7.1f}{r['data']:7.1f}{r['leak']:7.1f}{r['pers']:7.1f}{r['final']:7.1f}")
    print("\nby dataset (final vs plain):")
    for ds, n in Counter(q["dataset"] for q in ev).most_common():
        qq = [q for q in ev if q["dataset"] == ds]
        f, p = np.mean([S(q, final(q)) for q in qq]), np.mean([S(q, q["preds"]["plain"]) for q in qq])
        out["by_dataset"][ds] = {"N": n, "plain": p, "final": f, "has_data": sum(q["rel"] is not None for q in qq)}
        print(f"  {ds:22s} N {n:3d} with data {out['by_dataset'][ds]['has_data']:3d}  plain {p:6.1f}  final {f:6.1f}")
    (M.OUT / ("leak_strict_combine_report.json" if STRICT else "leak_combine_report.json")).write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
