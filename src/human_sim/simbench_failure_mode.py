"""Pop vs Grouped, or consensus vs divided? Diagnostics for the composition arms.

Arms (Haiku, both option orders, retr6 demos):
  C0  retr6_rev2                       baseline
  C1  C1_comp_direct                   + composition table, direct prediction
  C2  C2_comp_personas                 one call per group, mixed with REAL shares
  C3  equal-weight mix of C2's logged per-group answers (no extra calls)
Oracle (diagnostic only): TRUE same-question subgroup distributions mixed with TRUE shares,
only where those Grouped cells exist. Never a candidate.

Usage:
  PYTHONPATH=src python -m human_sim.simbench_failure_mode
"""

from __future__ import annotations

import json
import random
from collections import defaultdict

import numpy as np
import pandas as pd

from human_sim.simbench_ablate import (
    OUT_DIR,
    _as_dict,
    _composition,
    _country_of,
    _COUNTRY_KEYS,
    build_env,
    dataset_norms,
)

MODEL = "claude-haiku-4-5"
CUTS = (0.65, 0.84)


def _h(v: np.ndarray) -> float:
    q = v[v > 0]
    return float(-(q * np.log(q)).sum() / np.log(len(v))) if len(v) > 1 else 0.0


def _bin(h: float) -> str:
    return "consensus" if h < CUTS[0] else ("mixed" if h < CUTS[1] else "divided")


def _oracle_index(grouped: pd.DataFrame) -> dict:
    """(dataset, country, question, attribute) -> list of (value, size, answer)."""
    idx = defaultdict(list)
    for _, r in grouped.iterrows():
        vm = _as_dict(r["group_prompt_variable_map"])
        other = [k for k in vm if k not in _COUNTRY_KEYS]
        if len(other) == 1 and r["group_size"] and r["group_size"] > 0:
            idx[(r["dataset_name"], _country_of(vm), r["input_template"], other[0])].append(
                (str(vm[other[0]]), float(r["group_size"]), _as_dict(r["human_answer"]))
            )
    return idx


def load(which: str):
    sample, _, ctx = build_env(25, 100, 7, which)
    norms = (
        json.loads((OUT_DIR / "dataset_norms.json").read_text()) if which == "eval" else dataset_norms(sample)
    )
    suffix = "" if which == "eval" else "dev10x40"
    rows = {}
    for key, arm in (("C0", "retr6_rev2"), ("C1", "C1_comp_direct"), ("C2", "C2_comp_personas")):
        path = OUT_DIR / f"{arm}_{MODEL}_p25g100s7{suffix}.json"
        rows[key] = {r["i"]: r for r in json.loads(path.read_text())["rows"] if r.get("ok")}
    ids = sorted(set(rows["C1"]) & set(rows["C2"]) & set(rows["C0"]))
    grouped = pd.read_csv(OUT_DIR.parents[1] / "data" / "simbench" / "SimBenchGrouped.csv")
    oidx = _oracle_index(grouped)
    cases = []
    for i in ids:
        row = sample.iloc[i]
        keys = list(row["human_answer"].keys())
        vec = lambda d: np.array([d.get(k, 0.0) for k in keys], dtype=float) / max(sum(d.get(k, 0.0) for k in keys), 1e-12)  # noqa: E731
        human = vec(row["human_answer"])
        segs = rows["C2"][i].get("segments", [])
        c = {
            "i": i,
            "split": row["split"],
            "ds": row["dataset_name"],
            "human": human,
            "hH": _h(human),
            "norm": norms[row["dataset_name"]],
            "C0": vec(rows["C0"][i]["llm_answer"]),
            "C1": vec(rows["C1"][i]["llm_answer"]),
            "C2": vec(rows["C2"][i]["llm_answer"]),
            "C3": np.mean([vec(sg["dist"]) for sg in segs], axis=0) if segs else vec(rows["C2"][i]["llm_answer"]),
            "shares": [sg["share"] for sg in segs],
        }
        comp = _composition(row, ctx)
        if comp:
            att = comp[0]["attribute"]
            truth = oidx.get((row["dataset_name"], _country_of(row["group_prompt_variable_map"]), row["input_template"], att))
            wanted = {cell["value"] for cell in comp[0]["cells"]}
            truth = [t for t in (truth or []) if t[0] in wanted]
            if len(truth) >= 2:
                w = np.array([t[1] for t in truth])
                c["oracle"] = sum(wi * vec(t[2]) for wi, t in zip(w / w.sum(), truth))
        cases.append(c)
    return cases


def score(c: dict, k: str) -> float:
    return 100 * (1 - 0.5 * float(np.abs(c[k] - c["human"]).sum()) / c["norm"])


def ci(d: list[float]) -> list[float]:
    rng = random.Random(0)
    boots = sorted(float(np.mean([rng.choice(d) for _ in d])) for _ in range(1000))
    return [round(float(np.mean(d)), 2), round(boots[25], 2), round(boots[975], 2)]


def cell_report(cases: list[dict]) -> dict:
    out = {"n": len(cases)}
    if not cases:
        return out
    for k in ("C0", "C1", "C2", "C3"):
        out[k] = {
            "S": round(float(np.mean([score(c, k) for c in cases])), 2),
            "TVD": round(float(np.mean([0.5 * np.abs(c[k] - c["human"]).sum() for c in cases])), 4),
            "entropy_gap": round(float(np.mean([_h(c[k]) - c["hH"] for c in cases])), 3),
            "top_option_right": round(float(np.mean([np.argmax(c[k]) == np.argmax(c["human"]) for c in cases])), 3),
        }
        if k != "C0" and len(cases) >= 2:
            out[k]["vs_C0"] = ci([score(c, k) - score(c, "C0") for c in cases])
    if len(cases) >= 2:
        out["C2_vs_C3"] = ci([score(c, "C2") - score(c, "C3") for c in cases])
    return out


def main() -> None:
    report = {}
    for which in ("dev", "eval"):
        cases = load(which)
        cells = {}
        for sp in ("Pop", "Grouped", "all"):
            for b in ("consensus", "mixed", "divided", "all"):
                sel = [c for c in cases if (sp == "all" or c["split"] == sp) and (b == "all" or _bin(c["hH"]) == b)]
                cells[f"{sp}/{b}"] = cell_report(sel)
        unequal = [c for c in cases if c["shares"] and (max(c["shares"]) - min(c["shares"])) >= 0.1]
        oracle = [c for c in cases if "oracle" in c]
        report[which] = {
            "covered_questions": len(cases),
            "cells": cells,
            "weights_test_unequal_shares": cell_report(unequal) if unequal else {"n": 0},
            "oracle_ceiling": {
                "n": len(oracle),
                "S_oracle": round(float(np.mean([score(c, "oracle") for c in oracle])), 2) if oracle else None,
                "S_C2_same_questions": round(float(np.mean([score(c, "C2") for c in oracle])), 2) if oracle else None,
                "S_C0_same_questions": round(float(np.mean([score(c, "C0") for c in oracle])), 2) if oracle else None,
            },
        }
    print(json.dumps(report, indent=1))
    (OUT_DIR / "failure_mode_report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
