#!/usr/bin/env python3
"""Baseline vs single-change arms on one index set: CA (95% CI), paired dCA (bootstrap CI + exact McNemar p), OI, cost.

usage: arm_compare.py base=results/run_a arm1=results/run_b ... --indices @file [--md out.md] [--json out.json]
The first run is the baseline. Cost per pair = all of an arm's calls for the pair (including calls copied in from
another ledger at $0), re-priced at the list price of the model that served it (gemini-2.5-flash $0.30 / $2.50 per 1M in/out,
gemini-3.1-pro-preview $2 / $12; thinking tokens count as output), so it is the arm's
true per-pair cost, not the incremental spend.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_metrics import boot, ids_of, load  # noqa: E402

B = 10000
# list $/1M tokens (in, out); kept in sync with run_bench.PRICE
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-3.1-pro-preview": (2.00, 12.00),
         "claude-sonnet-4-6": (3.00, 15.00), "claude-haiku-4-5@20251001": (1.00, 5.00),
         "gpt-4o": (2.50, 10.00), "gpt-4.1-mini": (0.40, 1.60), "gpt-5-mini": (0.25, 2.00)}


def pair_cost(run: Path, ids: set[int]) -> float:
    per = defaultdict(float)
    for line in (run / "calls.jsonl").open():
        r = json.loads(line)
        try:
            i = int(r["key"].split("|")[0])
        except ValueError:
            continue
        if i in ids and not r["key"].split("|")[1] == "planner":
            pin, pout = PRICE.get(r.get("model") or "", PRICE["gemini-2.5-flash"])  # tuned endpoints bill as base Flash
            per[i] += r["tokens_in"] * pin * 1e-6 + r["tokens_out"] * pout * 1e-6
    return sum(per.values()) / max(1, len(per))


def mcnemar(a: list[float], b: list[float]) -> tuple[int, int, float]:
    """Exact two-sided McNemar (binomial on discordant pairs)."""
    n01 = sum(1 for x, y in zip(a, b) if x == 0 and y == 1)
    n10 = sum(1 for x, y in zip(a, b) if x == 1 and y == 0)
    n = n01 + n10
    if n == 0:
        return n01, n10, 1.0
    k = min(n01, n10)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n * 2
    return n01, n10, min(1.0, p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--indices", required=True)
    ap.add_argument("--md", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    keep = set(ids_of(args.indices))
    runs = [(s.split("=", 1)[0], Path(s.split("=", 1)[1])) for s in args.runs]
    data = {lab: load(p) for lab, p in runs}
    ids = sorted(keep.intersection(*(set(v) for v in data.values())))
    base_lab = runs[0][0]
    base = data[base_lab]
    pct = lambda x: f"{100 * x:.1f}"  # noqa: E731
    lines = [f"n = {len(ids)} pairs" + (f" ({len(keep) - len(ids)} missing in some run)" if len(ids) < len(keep) else ""), "",
             "| arm | CA [95% CI] | dCA vs base [95% CI] | McNemar p (n01/n10) | significant | AA | FA / SA | OI [95% CI] | dOI [95% CI] | $/pair |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    out = {}
    for lab, path in runs:
        sd = data[lab]
        ca = [sd[i]["ca"] for i in ids]
        oi = [sd[i]["oi"] for i in ids]
        lo, hi = boot(ca)
        olo, ohi = boot(oi)
        row = {"n": len(ids), "ca": sum(ca) / len(ids), "ca_ci": (lo, hi), "oi": sum(oi) / len(ids), "oi_ci": (olo, ohi),
               "aa": sum(sd[i]["aa"] for i in ids) / len(ids), "fa": sum(sd[i]["fa"] for i in ids) / len(ids),
               "sa": sum(sd[i]["sa"] for i in ids) / len(ids), "usd_per_pair": pair_cost(path, set(ids))}
        if lab != base_lab:
            bca = [base[i]["ca"] for i in ids]
            d = [x - y for x, y in zip(ca, bca)]
            dlo, dhi = boot(d, seed=1)
            n01, n10, p = mcnemar(bca, ca)
            do = [sd[i]["oi"] - base[i]["oi"] for i in ids]
            dolo, dohi = boot(do, seed=2)
            row.update({"dca": sum(d) / len(d), "dca_ci": (dlo, dhi), "mcnemar_p": p, "n01": n01, "n10": n10,
                        "doi": sum(do) / len(do), "doi_ci": (dolo, dohi), "significant": p < 0.05 and (dlo > 0 or dhi < 0)})
            dtxt = f"{100 * row['dca']:+.1f} [{100 * dlo:+.1f}, {100 * dhi:+.1f}]"
            ptxt = f"{p:.3f} ({n01}/{n10})"
            stxt = "yes" if row["significant"] else "no"
            dotxt = f"{100 * row['doi']:+.1f} [{100 * dolo:+.1f}, {100 * dohi:+.1f}]"
        else:
            dtxt = ptxt = stxt = dotxt = "(baseline)"
        out[lab] = row
        lines.append(f"| {lab} | {pct(row['ca'])} [{pct(lo)}, {pct(hi)}] | {dtxt} | {ptxt} | {stxt} | {pct(row['aa'])} | "
                     f"{pct(row['fa'])} / {pct(row['sa'])} | {pct(row['oi'])} [{pct(olo)}, {pct(ohi)}] | {dotxt} | "
                     f"{row['usd_per_pair']:.4f} |")
    lines += ["", "n01 = pairs the baseline got wrong (CA) and the arm right; n10 = the reverse. "
              "Significant = McNemar p < 0.05 and the bootstrap CI of dCA excludes 0."]
    text = "\n".join(lines)
    print(text)
    if args.md:
        Path(args.md).write_text(text + "\n")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
