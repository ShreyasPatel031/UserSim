#!/usr/bin/env python3
"""Per-study and fine-tuning cost projections from cost_per_pair.py --json output.

usage: cost_project.py cost.json [--md out.md]

Product study (3 products x 6 personas x 6 tasks): the comparison is our product vs 2 rivals = 2 pairs, each judged
by 6 personas in both orders (personas already exist from the study, so planner calls are excluded).
Prices: USD / 1M tokens, Vertex standard PayGo, <=200k context, as listed 2026-09-27 on
https://cloud.google.com/vertex-ai/generative-ai/pricing ; Batch/Flex are 50% of these.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MODELS = {  # (input, output, image tokens per image at default resolution, can thinking be off?)
    "gemini-2.5-flash": (0.30, 2.50, 258, True),
    "gemini-2.5-pro": (1.25, 10.00, 258, False),
    "gemini-3.8-flash intro (to 2026-12-31)": (0.75, 3.75, 1120, False),
    "gemini-3.8-flash (from 2027-01-01)": (1.50, 7.50, 1120, False),
    "gemini-3.1-pro-preview": (2.00, 12.00, 1120, False),
}
OBS_IMG = 258  # tokens per image observed on Vertex gemini-2.5-flash with 2 images per request
THINK = 500    # assumed thinking tokens per call where thinking cannot be turned off (2.5 Pro min budget 128)
TUNE = {"gemini-2.5-flash": 5.0, "gemini-3.5-flash": 10.0, "gemini-3.1-flash-lite": 3.0, "gemini-2.5-pro": 25.0}  # $/1M train tokens


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cost_json")
    ap.add_argument("--md", default="")
    args = ap.parse_args()
    d = json.loads(Path(args.cost_json).read_text())
    L = ["## Per pair and per product study (2 rival pairs x 6 personas x both orders; planner excluded)", "",
         "Token counts are measured on gemini-2.5-flash (thinking off, 2 images/call at ~258 tokens each). "
         f"'as measured' re-prices the same tokens; '+adj' adds {THINK} thinking tokens/call for models that cannot "
         "turn thinking off, and Gemini 3 default image tokens (1120/image instead of 258).", "",
         "| arm | calls/pair | in/pair | out/pair | model | $/pair as measured | $/pair +adj | $/study as measured | "
         "$/study +adj | $/study +adj, batch/flex |", "|---|---|---|---|---|---|---|---|---|---|"]
    for arm, v in d.items():
        pl = v["by_kind"].get("planner", {"calls_per_pair": 0, "in_per_call": 0, "out_per_call": 0})
        calls = v["calls_per_pair"] - pl["calls_per_pair"]
        tin = v["tin_per_pair"] - pl["calls_per_pair"] * pl["in_per_call"]
        tout = v["tout_per_pair"] - pl["calls_per_pair"] * pl["out_per_call"]
        for m, (pi, po, img, think_off) in MODELS.items():
            base = tin / 1e6 * pi + tout / 1e6 * po
            tin2 = tin + calls * 2 * (img - OBS_IMG)
            tout2 = tout + (0 if think_off else calls * THINK)
            adj = tin2 / 1e6 * pi + tout2 / 1e6 * po
            L.append(f"| {arm} | {calls:.1f} | {tin:,.0f} | {tout:,.0f} | {m} | {base:.4f} | {adj:.4f} | "
                     f"{2 * base:.3f} | {2 * adj:.3f} | {adj:.3f} |")
    # fine-tuning
    judge = d.get("S2strict", next(iter(d.values())))["by_kind"].get("judge", {"in_per_call": 890, "out_per_call": 98})
    gf = d.get("GFOCUS")
    ex = {"verdict-only (S2 judge call: 2 images + persona prompt -> ratings)": judge["in_per_call"] + judge["out_per_call"]}
    if gf:
        ev = gf["by_kind"]["argue:evaluator"]
        ex["one-call G-FOCUS distill (2 images + goal/diffs -> ranked reasons + verdict)"] = ev["in_per_call"] - 650 + ev["out_per_call"]
        ex["full G-FOCUS chain, all 5 stages as examples (per order)"] = (gf["tin_per_pair"] + gf["tout_per_pair"]) / 2
    L += ["", "## Supervised fine-tuning cost (training tokens = dataset tokens x epochs; 3 epochs)", "",
          "| example type | tokens/example | examples | " + " | ".join(f"{m} (${p}/1M)" for m, p in TUNE.items()) + " |",
          "|---|---|---|" + "---|" * len(TUNE)]
    for name, tok in ex.items():
        for n in (1000, 5000, 20000):
            L.append(f"| {name} | {tok:,.0f} | {n:,} | " + " | ".join(f"${n * tok * 3 / 1e6 * p:,.2f}" for p in TUNE.values()) + " |")
    text = "\n".join(L)
    print(text)
    if args.md:
        Path(args.md).write_text(text + "\n")


if __name__ == "__main__":
    main()
