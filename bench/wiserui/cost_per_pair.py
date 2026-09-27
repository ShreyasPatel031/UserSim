#!/usr/bin/env python3
"""Tokens and cost per pair for pairwise arms, from run ledgers (calls.jsonl: Vertex usage metadata per call).

usage: cost_per_pair.py label=results/run_dir ... --indices @final_indices.txt [--md out.md] [--json out.json]

Per pair: every call whose key starts with "<index>|" (planner included; planner records copied between ledgers
carry cost 0 but real token counts, so tokens are counted once per arm). A0 personas planned in results/full
(key usersim|<i>|-|planner|0) are added for pairs whose planner is not in the arm's ledger, when the arm uses personas.
Retried/errored calls: only the cached (final) record per key exists; errored calls have 0 tokens.
Projections re-price the SAME token counts; they do not model thinking tokens, image-token changes on Gemini 3
(1120 tokens per image by default vs ~258 on 2.5 multi-image requests), or verbosity differences between models.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

# USD per 1M tokens (input, output), Vertex standard PayGo <=200k context, as of 2026-09-27
# (https://cloud.google.com/vertex-ai/generative-ai/pricing). Batch/Flex = 50%.
PRICES = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-3.8-flash (intro to 2026-12-31, global)": (0.75, 3.75),
    "gemini-3.8-flash (from 2027-01-01, global)": (1.50, 7.50),
    "gemini-3.5-flash (global)": (1.50, 9.00),
    "gemini-3.1-pro-preview (global)": (2.00, 12.00),
}
A0 = Path("/workspace/bench/wiserui/results/full/calls.jsonl")


def ids_of(arg: str) -> list[int]:
    raw = Path(arg[1:]).read_text() if arg.startswith("@") else arg
    return [int(x) for x in raw.replace("\n", ",").split(",") if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("arms", nargs="+")
    ap.add_argument("--indices", required=True)
    ap.add_argument("--md", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    keep = set(ids_of(args.indices))
    a0 = {}
    for line in A0.open():
        r = json.loads(line)
        p = r["key"].split("|")
        if p[0] == "usersim" and len(p) > 3 and p[3] == "planner" and not r.get("error"):
            a0[int(p[1])] = (r["tokens_in"], r["tokens_out"])
    out, lines = {}, []
    lines += ["| arm | pairs | calls/pair | tokens in/pair | tokens out/pair | in/call | out/call | " +
              " | ".join(f"$/pair {m}" for m in PRICES) + " |", "|---" * (7 + len(PRICES)) + "|"]
    kinds_md = []
    for spec in args.arms:
        lab, path = spec.split("=", 1)
        per = defaultdict(lambda: [0, 0, 0])
        by_kind = defaultdict(lambda: [0, 0, 0])
        has_planner, uses_personas = set(), False
        for line in (Path(path) / "calls.jsonl").open():
            r = json.loads(line)
            p = r["key"].split("|")
            try:
                i = int(p[0])
            except ValueError:
                continue
            if i not in keep:
                continue
            k = p[1]
            if k == "planner":
                has_planner.add(i)
            if k == "judge" or (k == "argue" and p[3] != "single"):
                uses_personas = True
            kk = k if k != "argue" else "argue:" + ("evaluator" if "evaluator" in r["key"] else p[-1])
            for d in (per[i], by_kind[kk]):
                d[0] += 1
                d[1] += r["tokens_in"]
                d[2] += r["tokens_out"]
        if uses_personas:
            for i in per:
                if i not in has_planner and i in a0:
                    per[i][0] += 1
                    per[i][1] += a0[i][0]
                    per[i][2] += a0[i][1]
                    for j, v in enumerate((1, *a0[i])):
                        by_kind["planner"][j] += v
        n = len(per)
        calls = sum(v[0] for v in per.values()) / n
        tin = sum(v[1] for v in per.values()) / n
        tout = sum(v[2] for v in per.values()) / n
        cost = {m: tin / 1e6 * pi + tout / 1e6 * po for m, (pi, po) in PRICES.items()}
        out[lab] = {"pairs": n, "calls_per_pair": calls, "tin_per_pair": tin, "tout_per_pair": tout, "usd_per_pair": cost,
                    "by_kind": {k: {"calls_per_pair": v[0] / n, "in_per_call": v[1] / max(1, v[0]),
                                    "out_per_call": v[2] / max(1, v[0])} for k, v in by_kind.items()},
                    "pair_cost_p90_flash": sorted(v[1] * 0.3e-6 + v[2] * 2.5e-6 for v in per.values())[int(0.9 * n)]}
        lines.append(f"| {lab} | {n} | {calls:.1f} | {tin:,.0f} | {tout:,.0f} | {tin / calls:,.0f} | {tout / calls:,.0f} | " +
                     " | ".join(f"{c:.4f}" for c in cost.values()) + " |")
        for k, v in sorted(by_kind.items()):
            kinds_md.append(f"| {lab} | {k} | {v[0] / n:.2f} | {v[1] / max(1, v[0]):,.0f} | {v[2] / max(1, v[0]):,.0f} |")
    lines += ["", "| arm | call type | calls/pair | in/call | out/call |", "|---|---|---|---|---|", *kinds_md]
    text = "\n".join(lines)
    print(text)
    if args.md:
        Path(args.md).write_text(text + "\n")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
