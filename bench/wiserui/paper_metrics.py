#!/usr/bin/env python3
"""Paper-comparable Task-1 metrics (arXiv 2505.05026, repo eval/task1_eval.py) for pairwise runs, with 95% CIs.

usage: paper_metrics.py S2=results/pw_all_s2 S2strict=results/pw_all_s2strict --indices @final_indices.txt
       [--dev @dev_indices.txt] [--recovered @recovered_indices.txt] [--md out.md] [--json out.json]

Per pair, each presentation order gives one pick (mean X-Y rating over the personas in that order; tie = wrong):
  FA  accuracy with the winner shown first (paper's win_lose file)    SA  accuracy with the winner shown second (lose_win)
  AA  (FA + SA) / 2, the paper's "AA" (all 2N per-order answers)       CA  right in BOTH orders, the paper's headline (chance 25%)
  OI  order-invariant: one pick per pair from both orders together (p(A>B) from ratings averaged across orders);
      tie = 0.5 (chance 50%). Not in the paper.
CIs: 10k pair-level bootstrap (percentile). Paired bootstrap for B - A differences on CA / OI.
Views: all pairs (paper-comparable total), held-out (all minus the dev pairs used to pick the arm), per source,
and original-clean vs recovered-composite subsets.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

B = 10000


def ids_of(arg: str) -> list[int]:
    raw = Path(arg[1:]).read_text() if arg.startswith("@") else arg
    return [int(x) for x in raw.replace("\n", ",").split(",") if x.strip()]


def load(run: Path) -> dict[int, dict]:
    out = {}
    for line in (run / "pairs.jsonl").open():
        r = json.loads(line)
        win = "A" if r["a_is_win"] else "B"
        fa = sa = 0.0
        for o, ov in r["orders"].items():
            winner_first = (o == "ab") == (win == "A")
            ok = float(ov.get("pick_ab") == win)
            if winner_first:
                fa = ok
            else:
                sa = ok
        out[r["index"]] = {"source": r["source"], "fa": fa, "sa": sa, "ca": fa * sa, "aa": (fa + sa) / 2,
                           "oi": 1.0 if r["winner"] == win else 0.5 if r["winner"] == "tie" else 0.0}
    return out


def boot(vals: list[float], seed: int = 0) -> tuple[float, float]:
    rng, n = random.Random(seed), len(vals)
    bs = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return bs[int(0.025 * B)], bs[int(0.975 * B) - 1]


METRICS = ("ca", "aa", "fa", "sa", "oi")


def summ(sysd: dict[int, dict], ids: list[int]) -> dict:
    s = {"n": len(ids)}
    for m in METRICS:
        v = [sysd[i][m] for i in ids]
        s[m] = sum(v) / len(v)
        s[m + "_ci"] = boot(v)
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("systems", nargs="+")
    ap.add_argument("--indices", required=True)
    ap.add_argument("--dev", default="")
    ap.add_argument("--recovered", default="")
    ap.add_argument("--md", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    keep = set(ids_of(args.indices))
    systems = {}
    for s in args.systems:
        lab, p = s.split("=", 1)
        systems[lab] = load(Path(p))
    ids = sorted(keep.intersection(*(set(v) for v in systems.values())))
    missing = sorted(keep - set(ids))
    first = next(iter(systems.values()))
    dev = set(ids_of(args.dev)) if args.dev else set()
    rec = set(ids_of(args.recovered)) if args.recovered else set()
    views = [("all", ids)]
    if dev:
        views.append(("held-out (minus dev)", [i for i in ids if i not in dev]))
    for src in sorted({first[i]["source"] for i in ids}):
        views.append((f"source={src}", [i for i in ids if first[i]["source"] == src]))
        if dev:
            views.append((f"source={src}, held-out", [i for i in ids if first[i]["source"] == src and i not in dev]))
    if rec:
        views.append(("original clean pairs", [i for i in ids if i not in rec]))
        views.append(("recovered composites", [i for i in ids if i in rec]))
    pct = lambda x: f"{100 * x:.1f}"  # noqa: E731
    lines = [f"n = {len(ids)} pairs scored" + (f"; {len(missing)} requested but missing: {missing}" if missing else ""), "",
             "| view | n | arm | CA [95% CI] | AA [95% CI] | FA / SA | OI [95% CI] |", "|---|---|---|---|---|---|---|"]
    res = {}
    for name, vids in views:
        if not vids:
            continue
        for lab, sd in systems.items():
            s = summ(sd, vids)
            res[f"{name}|{lab}"] = s
            lines.append(f"| {name} | {s['n']} | {lab} | {pct(s['ca'])} [{pct(s['ca_ci'][0])}, {pct(s['ca_ci'][1])}] | "
                         f"{pct(s['aa'])} [{pct(s['aa_ci'][0])}, {pct(s['aa_ci'][1])}] | {pct(s['fa'])} / {pct(s['sa'])} | "
                         f"{pct(s['oi'])} [{pct(s['oi_ci'][0])}, {pct(s['oi_ci'][1])}] |")
    labs = list(systems)
    if len(labs) >= 2:
        lines += ["", "| view | comparison | dCA [95% CI] | dOI [95% CI] |", "|---|---|---|---|"]
        a, b = labs[0], labs[1]
        for name, vids in views[:2]:
            row = []
            for m in ("ca", "oi"):
                d = [systems[b][i][m] - systems[a][i][m] for i in vids]
                lo, hi = boot(d, seed=1)
                row.append(f"{100 * sum(d) / len(d):+.1f} [{100 * lo:+.1f}, {100 * hi:+.1f}]")
                res[f"{name}|{b}-{a}|{m}"] = (sum(d) / len(d), lo, hi)
            lines.append(f"| {name} | {b} - {a} | {row[0]} | {row[1]} |")
    text = "\n".join(lines)
    print(text)
    if args.md:
        Path(args.md).write_text(text + "\n")
    if args.json:
        Path(args.json).write_text(json.dumps({"n": len(ids), "missing": missing, "views": res}, indent=1))


if __name__ == "__main__":
    main()
