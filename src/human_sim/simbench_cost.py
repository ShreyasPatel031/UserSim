"""Estimate SimBench API cost for Gemini Flash / Flash-Lite (verbalized protocol).

Official SimBench Gemini path = 1 call per test case, JSON % distribution,
max_output_tokens=250 (see vendor/SimBench_release/generate_answers.py).

Usage:
  PYTHONPATH=src python -m human_sim.simbench_cost
"""

from __future__ import annotations

import pickle
from pathlib import Path

from config import ROOT

DATA = ROOT / "data" / "simbench"

# USD / 1M tokens (Google list prices)
PRICES = {
    "gemini-2.5-flash": {"in": 0.30, "out": 2.50},
    "gemini-2.5-flash-lite": {"in": 0.10, "out": 0.40},
}


def _generate_prompt(row) -> tuple[str, str]:
    system = "You are a group of individuals with these shared characteristics:\n"
    system += str(row["group_prompt_template"])
    user = "**Question**: " + row["input_template"] + "\n"
    var_map = row.get("group_prompt_variable_map") or {}
    if isinstance(var_map, dict):
        for variable, value in var_map.items():
            system = system.replace(f"{{{variable}}}", str(value))
    keys = list(row["human_answer"].keys())
    json_format_str = "{" + ", ".join(f'"{k}": X' for k in keys) + "}"
    user += (
        "\nEstimate what percentage of your group would choose each option. "
        "Follow these rules:\n"
        "1. Use whole numbers from 0 to 100\n"
        "2. Ensure the percentages sum to exactly 100\n"
        "3. Only include the numbers (no % symbols)\n"
        f"4. Use this exact valid JSON format: {json_format_str} and do NOT include anything else.\n"
        "5. Only output your final answer and nothing else. No explanations or intermediate steps are needed.\n"
        "Replace X with your estimated percentages for each option.\n"
        "**Answer**:"
    )
    return system, user


def _load(name: str):
    path = DATA / f"{name}.pkl"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Download with:\n"
            "  python -m human_sim.simbench_setup"
        )
    with path.open("rb") as f:
        return pickle.load(f)


def estimate(chars_per_token: float = 4.0, out_tokens_avg: float | None = None) -> dict:
    pops = {
        "SimBenchPop": _load("SimBenchPop"),
        "SimBenchGrouped": _load("SimBenchGrouped"),
    }
    rows = []
    for split, df in pops.items():
        in_chars = 0
        tight_out = 0
        n = len(df)
        for _, row in df.iterrows():
            s, u = _generate_prompt(row)
            in_chars += len(s) + len(u)
            n_opt = len(row["human_answer"])
            tight_out += min(250 * 4, 30 + 18 * max(n_opt, 2))
        in_m = (in_chars / chars_per_token) / 1e6
        if out_tokens_avg is None:
            out_m = (tight_out / chars_per_token) / 1e6
            out_note = "tight JSON"
        else:
            out_m = (n * out_tokens_avg) / 1e6
            out_note = f"avg_out={out_tokens_avg}"
        costs = {
            model: round(in_m * p["in"] + out_m * p["out"], 2)
            for model, p in PRICES.items()
        }
        rows.append(
            {
                "split": split,
                "n": n,
                "in_MTok": round(in_m, 3),
                "out_MTok": round(out_m, 3),
                "out_note": out_note,
                **costs,
            }
        )

    # combined
    n = sum(r["n"] for r in rows)
    in_m = sum(r["in_MTok"] for r in rows)
    out_m = sum(r["out_MTok"] for r in rows)
    costs = {
        model: round(in_m * p["in"] + out_m * p["out"], 2)
        for model, p in PRICES.items()
    }
    rows.append(
        {
            "split": "BOTH (full)",
            "n": n,
            "in_MTok": round(in_m, 3),
            "out_MTok": round(out_m, 3),
            "out_note": rows[0]["out_note"],
            **costs,
        }
    )
    return {"chars_per_token": chars_per_token, "rows": rows, "prices": PRICES}


def main() -> None:
    print("SimBench cost estimate (verbalized = 1 call / case)\n")
    print("Prices USD / 1M tok:")
    for m, p in PRICES.items():
        print(f"  {m}: in ${p['in']:.2f}  out ${p['out']:.2f}")
    print()

    for label, kwargs in [
        ("Tight JSON output (~4 chars/tok)", {"chars_per_token": 4.0}),
        ("Conservative tokenization (~3.2 chars/tok)", {"chars_per_token": 3.2}),
        ("If model averages 100 out tokens (verbosity/retries)", {"out_tokens_avg": 100.0}),
        ("Worst case avg 250 out tokens (max_output_tokens)", {"out_tokens_avg": 250.0}),
    ]:
        est = estimate(**kwargs)
        print(f"--- {label} ---")
        for r in est["rows"]:
            print(
                f"  {r['split']:16} n={r['n']:5}  "
                f"in={r['in_MTok']:.3f}M out={r['out_MTok']:.3f}M  "
                f"Flash ${r['gemini-2.5-flash']:.2f}  "
                f"Lite ${r['gemini-2.5-flash-lite']:.2f}"
            )
        print()

    print("Protocol notes:")
    print("  - Official Gemini path uses prompt_method=verbalized (distribution JSON).")
    print("  - max_output_tokens=250 in vendor/SimBench_release/generate_answers.py")
    print("  - Add ~5–15% for parse retries.")
    print("  - Data: data/simbench/{SimBenchPop,SimBenchGrouped}.pkl")
    print("  - Upstream: vendor/SimBench_release + https://huggingface.co/datasets/pitehu/SimBench")


if __name__ == "__main__":
    main()
