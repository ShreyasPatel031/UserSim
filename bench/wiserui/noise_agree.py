#!/usr/bin/env python3
"""Run-to-run repeatability of one judge setup: two independent runs of the same flags on the same pairs.

usage: noise_agree.py "label=results/run1,results/run2" ... --indices @dev_indices.txt [--md out.md] [--json out.json]
Per option: pairs with the same per-pair CA outcome (right in both orders or not), pairs with the same picks in BOTH
orders, per-order pick agreement (2N picks), same order-invariant winner, CA of each run, and $/pair (mean of the two
runs; all calls for the pair re-priced at gemini-2.5-flash list price, including calls copied in from another ledger).
CIs: 10k pair-level bootstrap (percentile).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arm_compare import pair_cost  # noqa: E402
from paper_metrics import boot, ids_of  # noqa: E402


def picks(run: Path) -> dict[int, dict]:
    out = {}
    for line in (run / "pairs.jsonl").open():
        r = json.loads(line)
        win = "A" if r["a_is_win"] else "B"
        po = {o: ov.get("pick_ab", "tie") for o, ov in r["orders"].items()}
        ca = float(all(po.get(o) == win for o in ("ab", "ba")))
        out[r["index"]] = {"po": po, "ca": ca, "winner": r["winner"]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("options", nargs="+")
    ap.add_argument("--indices", required=True)
    ap.add_argument("--md", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    keep = set(ids_of(args.indices))
    pct = lambda x: f"{100 * x:.1f}"  # noqa: E731
    lines = ["| option | same CA outcome [95% CI] | same picks, both orders [95% CI] | per-order pick agreement | "
             "same OI winner | CA run 1 | CA run 2 | $/pair |", "|---|---|---|---|---|---|---|---|"]
    res = {}
    for spec in args.options:
        lab, paths = spec.split("=", 1)
        r1, r2 = (Path(p) for p in paths.split(","))
        a, b = picks(r1), picks(r2)
        ids = sorted(keep & set(a) & set(b))
        same_ca = [float(a[i]["ca"] == b[i]["ca"]) for i in ids]
        same_po = [float(a[i]["po"] == b[i]["po"]) for i in ids]
        per_o = [float(a[i]["po"].get(o) == b[i]["po"].get(o)) for i in ids for o in ("ab", "ba")]
        same_w = [float(a[i]["winner"] == b[i]["winner"]) for i in ids]
        ca1, ca2 = (sum(x[i]["ca"] for i in ids) / len(ids) for x in (a, b))
        cost = (pair_cost(r1, set(ids)) + pair_cost(r2, set(ids))) / 2
        row = {"n": len(ids), "same_ca": sum(same_ca) / len(ids), "same_ca_ci": boot(same_ca),
               "same_picks": sum(same_po) / len(ids), "same_picks_ci": boot(same_po), "per_order": sum(per_o) / len(per_o),
               "same_oi_winner": sum(same_w) / len(ids), "ca_1": ca1, "ca_2": ca2, "usd_per_pair": cost,
               "n_same_ca": int(sum(same_ca)), "n_same_picks": int(sum(same_po))}
        res[lab] = row
        lo, hi = row["same_ca_ci"]
        plo, phi = row["same_picks_ci"]
        lines.append(f"| {lab} | {row['n_same_ca']}/{len(ids)} = {pct(row['same_ca'])} [{pct(lo)}, {pct(hi)}] | "
                     f"{row['n_same_picks']}/{len(ids)} = {pct(row['same_picks'])} [{pct(plo)}, {pct(phi)}] | "
                     f"{pct(row['per_order'])} | {pct(row['same_oi_winner'])} | {pct(ca1)} | {pct(ca2)} | {cost:.4f} |")
    text = "\n".join(lines)
    print(text)
    if args.md:
        Path(args.md).write_text(text + "\n")
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
