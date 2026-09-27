#!/usr/bin/env python3
"""Vanilla single-call models vs our judge on one index set (VANILLA_COMPARE_REPORT.md).

usage: vanilla_compare.py ours=results/gfocus_t0_all252 gpt-4o=results/van_gpt4o ... --indices @final_indices_main.txt
       [--md out.md] [--json out.json]
The first run is ours (the reference for the paired tests). Per run: CA [95% CI], OI, FA / SA, unparsed per-order
answers (counted wrong; an order with no parsed answer never matches the winner), $/pair and total $ (every call for the
selected pairs at its model's list price), wall time (first to last call in the ledger, calls copied in at $0 excluded),
and vs ours: paired dCA (10k bootstrap CI) + exact McNemar p (n01 = ours wrong / model right, n10 = the reverse).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arm_compare import PRICE, mcnemar  # noqa: E402
from paper_metrics import boot, ids_of, load  # noqa: E402


def ledger_stats(run: Path, ids: set[int]) -> dict:
    cost, ts, n = 0.0, [], 0
    for line in (run / "calls.jsonl").open():
        r = json.loads(line)
        try:
            i = int(r["key"].split("|")[0])
        except ValueError:
            continue
        if i not in ids:
            continue
        pin, pout = PRICE.get(r.get("model") or "", PRICE["gemini-2.5-flash"])
        cost += r["tokens_in"] * pin * 1e-6 + r["tokens_out"] * pout * 1e-6
        if not r.get("copied_from"):
            ts += [r["ts"] - r.get("secs", 0), r["ts"]]
            n += 1
    return {"cost": cost, "wall_s": (max(ts) - min(ts)) if ts else 0.0, "new_calls": n}


def unparsed(run: Path, ids: set[int]) -> int:
    bad = 0
    for line in (run / "pairs.jsonl").open():
        r = json.loads(line)
        if r["index"] in ids:
            bad += sum(not j["ok"] for j in r["judgments"]) + (2 - len(r["judgments"]))
    return bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--indices", required=True)
    ap.add_argument("--md", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    runs = [(s.split("=", 1)[0], Path(s.split("=", 1)[1])) for s in a.runs]
    data = {lab: load(p) for lab, p in runs}
    ids = sorted(set(ids_of(a.indices)).intersection(*(set(v) for v in data.values())))
    ours_lab = runs[0][0]
    pct = lambda x: f"{100 * x:.1f}"  # noqa: E731
    lines = [f"n = {len(ids)} pairs", "",
             "| system | CA [95% CI] | OI | FA / SA | unparsed (of 2n) | $/pair | total $ | wall | dCA vs ours [95% CI] | McNemar p (ours-wrong-model-right / reverse) | ours significantly better? |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    out = {}
    for lab, path in runs:
        sd = data[lab]
        ca = [sd[i]["ca"] for i in ids]
        lo, hi = boot(ca)
        st = ledger_stats(path, set(ids))
        row = {"ca": sum(ca) / len(ids), "ca_ci": (lo, hi), "oi": sum(sd[i]["oi"] for i in ids) / len(ids),
               "fa": sum(sd[i]["fa"] for i in ids) / len(ids), "sa": sum(sd[i]["sa"] for i in ids) / len(ids),
               "unparsed": unparsed(path, set(ids)), "usd_per_pair": st["cost"] / len(ids), "usd_total": st["cost"],
               "wall_s": st["wall_s"]}
        if lab != ours_lab:
            oca = [data[ours_lab][i]["ca"] for i in ids]
            d = [x - y for x, y in zip(ca, oca)]
            dlo, dhi = boot(d, seed=1)
            n01, n10, p = mcnemar(oca, ca)
            better = p < 0.05 and dhi < 0
            row.update({"dca": sum(d) / len(d), "dca_ci": (dlo, dhi), "mcnemar_p": p, "n01": n01, "n10": n10,
                        "ours_better": better})
            cmp = (f"{100 * row['dca']:+.1f} [{100 * dlo:+.1f}, {100 * dhi:+.1f}] | {p:.2g} ({n01}/{n10}) | "
                   f"{'yes' if better else 'no'}")
        else:
            cmp = "(reference) | | "
        out[lab] = row
        lines.append(f"| {lab} | {pct(row['ca'])} [{pct(lo)}, {pct(hi)}] | {pct(row['oi'])} | {pct(row['fa'])} / {pct(row['sa'])} | "
                     f"{row['unparsed']} | {row['usd_per_pair']:.4f} | {row['usd_total']:.2f} | {row['wall_s']:.0f} s | {cmp} |")
    text = "\n".join(lines)
    print(text)
    if a.md:
        Path(a.md).write_text(text + "\n")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
