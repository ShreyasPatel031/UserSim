"""Compare harnesses within each model on the dev set (no cross-model mixing).

Harnesses: three aimed at consensus questions (retr6, retr6_vs3, P_adapt) and three at
divided questions (panel+segments mix, P_groundall5, B_n3_soft_rev2), plus the plain
persona prompt as reference. The panel+segments mix uses fixed weights from the Haiku dev
fit (0.4 panel / 0.6 reversed-order segments), so it is not tuned on the other models.

Usage:
  PYTHONPATH=src python -m human_sim.simbench_harness_eval
"""

from __future__ import annotations

import json
import random

import numpy as np

from human_sim.simbench_ablate import OUT_DIR, build_env, dataset_norms

MODELS = ["claude-haiku-4-5", "claude-sonnet-4-6", "claude-sonnet-5-5", "gemini-2.5-flash"]
ARMS = ["base", "retr6", "retr6_vs3", "P_adapt", "P_groundall5", "B_n3_soft_rev2"]
MIX = {"P_groundall5": 0.4, "B_n3_soft_rev2": 0.6}
HARNESSES = {
    "persona prompt only": ("base",),
    "C1 retr6": ("retr6",),
    "C2 retr6_vs3": ("retr6_vs3",),
    "C3 P_adapt": ("P_adapt",),
    "D1 panel+segments (0.4/0.6)": ("mix",),
    "D2 P_groundall5": ("P_groundall5",),
    "D3 B_n3_soft_rev2": ("B_n3_soft_rev2",),
}
CUTS = (0.65, 0.84)
BINS = {
    "all": lambda c: True,
    "consensus": lambda c: c["hH"] < CUTS[0],
    "mixed": lambda c: CUTS[0] <= c["hH"] < CUTS[1],
    "divided": lambda c: c["hH"] >= CUTS[1],
}


def load(model: str, norms: dict) -> list[dict]:
    data = {}
    for a in ARMS:
        path = OUT_DIR / f"{a}_{model}_p25g100s7dev10x40.json"
        if path.exists():
            data[a] = {r["i"]: r for r in json.loads(path.read_text())["rows"] if r.get("ok")}
    ids = sorted(set.intersection(*[set(v) for v in data.values()]))
    cases = []
    for i in ids:
        first = next(iter(data.values()))[i]
        keys = list(first["human_answer"])
        vec = lambda d: np.array([d[k] for k in keys], dtype=float) / sum(d[k] for k in keys)  # noqa: E731
        human = vec(first["human_answer"])
        q = human[human > 0]
        c = {
            "i": i,
            "human": human,
            "norm": norms[first["dataset_name"]],
            "hH": float(-(q * np.log(q)).sum() / np.log(len(human))) if len(human) > 1 else 0.0,
            **{a: vec(data[a][i]["llm_answer"]) for a in data},
        }
        if all(k in c for k in MIX):
            c["mix"] = sum(w * c[k] for k, w in MIX.items())
        cases.append(c)
    return cases


def score(c: dict, key: str) -> float:
    return 100 * (1 - 0.5 * float(np.abs(c[key] - c["human"]).sum()) / c["norm"])


def ci(cases, a, b, cond) -> list[float]:
    d = [score(c, a) - score(c, b) for c in cases if cond(c)]
    rng = random.Random(0)
    boots = sorted(float(np.mean([rng.choice(d) for _ in d])) for _ in range(1000))
    return [round(float(np.mean(d)), 2), round(boots[25], 2), round(boots[975], 2)]


def main() -> None:
    sample, _, _ = build_env(25, 100, 7, "dev")
    norms = dataset_norms(sample)
    out = {}
    for model in MODELS:
        cases = load(model, norms)
        rows = {}
        for name, (key,) in HARNESSES.items():
            if cases and key in cases[0]:
                rows[name] = {b: round(float(np.mean([score(c, key) for c in cases if f(c)])), 2) for b, f in BINS.items()}
        cmp = {}
        if cases and "mix" in cases[0]:
            cmp["D1 vs retr6 (divided)"] = ci(cases, "mix", "retr6", BINS["divided"])
            cmp["D1 vs P_groundall5 (divided)"] = ci(cases, "mix", "P_groundall5", BINS["divided"])
        if cases and "retr6_vs3" in cases[0]:
            cmp["C2 vs retr6 (consensus)"] = ci(cases, "retr6_vs3", "retr6", BINS["consensus"])
        if cases and "P_adapt" in cases[0]:
            cmp["C3 vs retr6 (consensus)"] = ci(cases, "P_adapt", "retr6", BINS["consensus"])
        out[model] = {"n": len(cases), "harnesses": rows, "paired": cmp}
        print(f"\n=== {model} (paired dev n={len(cases)}) ===")
        print(f"{'harness':30}" + "".join(f"{b:>11}" for b in BINS))
        for name, r in rows.items():
            print(f"{name:30}" + "".join(f"{r[b]:11.1f}" for b in BINS))
        for k, v in cmp.items():
            print(f"  {k}: {v[0]:+.1f} [{v[1]:+.1f}, {v[2]:+.1f}]")
    (OUT_DIR / "harness_eval_dev.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
