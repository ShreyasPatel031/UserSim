"""Mixtures of logged arms (across prompts and models), fitted on DEV, scored on EVAL.

Each candidate is a fixed list of components; weights are searched on a 0.1 simplex grid
on the dev set only (optionally separately for questions whose retrieved neighbours agree
vs disagree), then applied unchanged to the full eval set. Every component stays a visible
part of the answer, with its weight.

Usage:
  PYTHONPATH=src python -m human_sim.simbench_mix
"""

from __future__ import annotations

import itertools
import json
import random
from collections import defaultdict

import numpy as np

from human_sim.simbench_ablate import OUT_DIR, _demo_pool, _rank_by_similarity, build_env

H, G = "claude-haiku-4-5", "gemini-2.5-flash"
COMPONENTS = {
    "retr6": ("retr6", H),
    "retr6_rev2": ("retr6_rev2", H),
    "B_n3_soft": ("B_n3_soft", H),
    "B_rev2": ("B_n3_soft_rev2", H),
    "panel": ("P_groundall5", H),
    "G_retr6": ("retr6", G),
}
CANDIDATES = [
    # (name, components, objective, split weights by neighbour agreement)
    ("divided: panel+B_n3_soft", ["panel", "B_n3_soft"], "divided", False),
    ("divided: panel+B_rev2", ["panel", "B_rev2"], "divided", False),
    ("total: panel+retr6 (previous blend)", ["panel", "retr6"], "all", True),
    ("total: retr6_rev2+G_retr6", ["retr6_rev2", "G_retr6"], "all", False),
    ("total: retr6_rev2+G_retr6+panel", ["retr6_rev2", "G_retr6", "panel"], "all", False),
    ("total: retr6_rev2+G_retr6+panel+B_rev2", ["retr6_rev2", "G_retr6", "panel", "B_rev2"], "all", False),
    ("total: G_retr6+panel+B_rev2 (by nbr)", ["G_retr6", "panel", "B_rev2"], "all", True),
]
CUTS = (0.65, 0.84)
BINS = {
    "all": lambda c: True,
    "consensus": lambda c: c["hH"] < CUTS[0],
    "mixed": lambda c: CUTS[0] <= c["hH"] < CUTS[1],
    "divided": lambda c: c["hH"] >= CUTS[1],
}


def load(which: str, suffix: str, norms: dict | None) -> list[dict]:
    data = {
        k: {r["i"]: r for r in json.loads((OUT_DIR / f"{a}_{m}_p25g100s7{suffix}.json").read_text())["rows"] if r.get("ok")}
        for k, (a, m) in COMPONENTS.items()
    }
    ids = sorted(set.intersection(*[set(v) for v in data.values()]))
    sample, _, ctx = build_env(25, 100, 7, which)
    cases = []
    for i in ids:
        keys = list(data["retr6"][i]["human_answer"])
        vec = lambda d: np.array([d[k] for k in keys], dtype=float) / sum(d[k] for k in keys)  # noqa: E731
        human = vec(data["retr6"][i]["human_answer"])
        q = human[human > 0]
        row = sample.iloc[i]
        nbrs = _rank_by_similarity(row, _demo_pool(row, ctx), ctx)[:6]
        cases.append(
            {
                "ds": data["retr6"][i]["dataset_name"],
                "human": human,
                "hH": float(-(q * np.log(q)).sum() / np.log(len(human))) if len(human) > 1 else 0.0,
                "nbr_h": float(np.mean([d["h"] for d in nbrs])) if nbrs else 0.7,
                **{k: vec(data[k][i]["llm_answer"]) for k in COMPONENTS},
            }
        )
    if norms is None:
        acc = defaultdict(list)
        for c in cases:
            acc[c["ds"]].append(0.5 * float(np.abs(c["human"] - 1 / len(c["human"])).sum()))
        norms = {k: float(np.mean(v)) for k, v in acc.items()}
    for c in cases:
        c["norm"] = norms[c["ds"]]
    return cases


def score(c: dict, pred: np.ndarray) -> float:
    return 100 * (1 - 0.5 * float(np.abs(pred - c["human"]).sum()) / c["norm"])


def _grid(n: int):
    steps = np.round(np.arange(0, 1.01, 0.1), 1)
    return [w for w in itertools.product(*[steps] * n) if abs(sum(w) - 1) < 1e-6]


def fit(dev: list[dict], comps: list[str], objective: str, by_nbr: bool):
    grid = _grid(len(comps))
    mix = lambda c, w: sum(wi * c[k] for wi, k in zip(w, comps))  # noqa: E731
    pool = [c for c in dev if BINS[objective](c)]
    if not by_nbr:
        w = max(grid, key=lambda w: np.mean([score(c, mix(c, w)) for c in pool]))
        return (lambda c: mix(c, w)), {"weights": dict(zip(comps, w))}
    edge = float(np.median([c["nbr_h"] for c in dev]))
    ws = {
        b: max(grid, key=lambda w: np.mean([score(c, mix(c, w)) for c in pool if (c["nbr_h"] >= edge) == b]))
        for b in (False, True)
    }
    return (lambda c: mix(c, ws[c["nbr_h"] >= edge])), {
        "nbr_entropy_edge": round(edge, 3),
        "weights_when_neighbours_agree": dict(zip(comps, ws[False])),
        "weights_when_neighbours_split": dict(zip(comps, ws[True])),
    }


def table(cases: list[dict], f) -> dict:
    return {b: round(float(np.mean([f(c) for c in cases if p(c)])), 2) for b, p in BINS.items()}


def ci(cases: list[dict], f, g, cond=lambda c: True) -> list[float]:
    d = [f(c) - g(c) for c in cases if cond(c)]
    rng = random.Random(0)
    boots = sorted(float(np.mean([rng.choice(d) for _ in d])) for _ in range(1000))
    return [round(float(np.mean(d)), 2), round(boots[25], 2), round(boots[975], 2)]


def main() -> None:
    dev = load("dev", "dev10x40", None)
    ev = load("eval", "", json.loads((OUT_DIR / "dataset_norms.json").read_text()))
    out = {"eval_n": len(ev), "single": {}, "mixes": {}}
    for k in COMPONENTS:
        out["single"][k] = table(ev, lambda c, k=k: score(c, c[k]))
    preds = {}
    for name, comps, objective, by_nbr in CANDIDATES:
        pred, info = fit(dev, comps, objective, by_nbr)
        preds[name] = pred
        out["mixes"][name] = {"fitted_on_dev": info, "eval": table(ev, lambda c, p=pred: score(c, p(c)))}
    best_total = "total: retr6_rev2+G_retr6+panel+B_rev2"
    prev = "total: panel+retr6 (previous blend)"
    div = "divided: panel+B_rev2"
    s = lambda name: (lambda c: score(c, preds[name](c)))  # noqa: E731
    single = lambda k: (lambda c: score(c, c[k]))  # noqa: E731
    out["paired_ci"] = {
        f"{best_total} vs previous blend": ci(ev, s(best_total), s(prev)),
        f"{best_total} vs G_retr6": ci(ev, s(best_total), single("G_retr6")),
        f"{div} vs panel (divided)": ci(ev, s(div), single("panel"), BINS["divided"]),
        f"{div} vs B_n3_soft (divided)": ci(ev, s(div), single("B_n3_soft"), BINS["divided"]),
        f"{best_total} vs panel (divided)": ci(ev, s(best_total), single("panel"), BINS["divided"]),
    }
    print(json.dumps(out, indent=1))
    (OUT_DIR / "mix_report.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
