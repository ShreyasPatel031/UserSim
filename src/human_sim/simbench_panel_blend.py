"""Close the persona panel's consensus gap without losing divided questions.

Two combiners over logged runs, both fitted on the DEV set only and applied unchanged
to the full EVAL set:
  route : run P_adapt when the 6 retrieved neighbours agree (mean entropy below a
          threshold), else P_groundall5.
  blend : add the direct grounded estimate (retr6) to the panel as one more visible
          component; its weight depends on how much the neighbours agree (thirds of
          neighbour entropy on dev).

Usage:
  PYTHONPATH=src python -m human_sim.simbench_panel_blend
"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict

import numpy as np

from human_sim.simbench_ablate import OUT_DIR, _demo_pool, _rank_by_similarity, build_env

MODEL = "claude-haiku-4-5"
DEV_TAG = f"{MODEL}_p25g100s7dev10x40"
EVAL_TAG = f"{MODEL}_p25g100s7"
CUTS = (0.65, 0.84)
ALPHAS = np.linspace(0, 1, 11)


def _h(p: np.ndarray) -> float:
    q = p[p > 0]
    return float(-(q * np.log(q)).sum() / math.log(len(p))) if len(p) > 1 else 0.0


def load(tag: str, which: str, arms: list[str], norms: dict | None = None) -> list[dict]:
    data = {
        a: {r["i"]: r for r in json.loads((OUT_DIR / f"{a}_{tag}.json").read_text())["rows"] if r.get("ok")}
        for a in arms
    }
    ids = sorted(set.intersection(*[set(v) for v in data.values()]))
    sample, _, ctx = build_env(25, 100, 7, which)
    cases = []
    for i in ids:
        keys = list(data[arms[0]][i]["human_answer"])
        vec = lambda d: np.array([d[k] for k in keys], dtype=float) / sum(d[k] for k in keys)  # noqa: E731
        row = sample.iloc[i]
        nbrs = _rank_by_similarity(row, _demo_pool(row, ctx), ctx)[:6]
        human = vec(data[arms[0]][i]["human_answer"])
        cases.append(
            {
                "i": i,
                "ds": data[arms[0]][i]["dataset_name"],
                "human": human,
                "hH": _h(human),
                "nbr_h": float(np.mean([d["h"] for d in nbrs])) if nbrs else 0.7,
                **{a: vec(data[a][i]["llm_answer"]) for a in arms},
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


def by_bin(cases: list[dict], f) -> dict:
    lo, hi = CUTS
    pick = {
        "all": lambda c: True,
        "consensus": lambda c: c["hH"] < lo,
        "mixed": lambda c: lo <= c["hH"] < hi,
        "divided": lambda c: c["hH"] >= hi,
    }
    return {k: round(float(np.mean([f(c) for c in cases if p(c)])), 2) for k, p in pick.items()}


def paired_ci(cases: list[dict], f, g) -> list[float]:
    d = [f(c) - g(c) for c in cases]
    rng = random.Random(0)
    boots = sorted(float(np.mean([rng.choice(d) for _ in d])) for _ in range(1000))
    return [round(float(np.mean(d)), 2), round(boots[25], 2), round(boots[975], 2)]


def main() -> None:
    arms = ["retr6", "P_groundall5", "P_adapt"]
    dev = load(DEV_TAG, "dev", arms)
    ev = load(EVAL_TAG, "eval", arms, json.loads((OUT_DIR / "dataset_norms.json").read_text()))

    # route: threshold on neighbour entropy, fitted on dev
    cand = np.quantile([c["nbr_h"] for c in dev], np.linspace(0.05, 0.95, 19))
    route_pred = lambda c, t: c["P_adapt"] if c["nbr_h"] < t else c["P_groundall5"]  # noqa: E731
    th = float(max(cand, key=lambda t: np.mean([score(c, route_pred(c, t)) for c in dev])))

    # blend: retr6 weight per third of neighbour entropy, fitted on dev
    edges = list(np.quantile([c["nbr_h"] for c in dev], [1 / 3, 2 / 3]))
    nb = lambda c: sum(c["nbr_h"] >= e for e in edges)  # noqa: E731
    blend_pred = lambda c, a: a * c["retr6"] + (1 - a) * c["P_groundall5"]  # noqa: E731
    alpha = {
        b: float(max(ALPHAS, key=lambda a: np.mean([score(c, blend_pred(c, a)) for c in dev if nb(c) == b])))
        for b in range(3)
    }

    methods = {
        "retr6": lambda c: score(c, c["retr6"]),
        "P_groundall5": lambda c: score(c, c["P_groundall5"]),
        "P_adapt": lambda c: score(c, c["P_adapt"]),
        "route": lambda c: score(c, route_pred(c, th)),
        "blend": lambda c: score(c, blend_pred(c, alpha[nb(c)])),
    }
    out = {
        "fitted_on_dev": {
            "route_threshold_nbr_entropy": round(th, 3),
            "blend_nbr_entropy_edges": [round(e, 3) for e in edges],
            "blend_retr6_weight_by_nbr_third": [alpha[b] for b in range(3)],
        },
        "eval_n": len(ev),
        "eval_route_share_P_adapt": round(float(np.mean([c["nbr_h"] < th for c in ev])), 3),
        "eval": {k: by_bin(ev, f) for k, f in methods.items()},
        "eval_paired_ci": {
            "blend_vs_retr6": paired_ci(ev, methods["blend"], methods["retr6"]),
            "blend_vs_P_groundall5": paired_ci(ev, methods["blend"], methods["P_groundall5"]),
            "route_vs_P_groundall5": paired_ci(ev, methods["route"], methods["P_groundall5"]),
        },
    }
    print(json.dumps(out, indent=1))
    (OUT_DIR / "panel_blend_report.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
