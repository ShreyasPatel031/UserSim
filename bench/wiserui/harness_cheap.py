#!/usr/bin/env python3
"""Harness lift on cheap models (HARNESS_CHEAP_REPORT.md): graded both-order harness arms vs each model's own plain run.

usage: harness_cheap.py MODEL=PLAIN_DIR,ARM=DIR[,ARM=DIR...] [...] [--indices @fullset/final_indices_main.txt]
       [--dev @dev_indices.txt] [--md out.md] [--json out.json]
e.g.   luna=results/van_gpt6luna,h1=results/hc_luna_h1,h1_debias=results/hc_luna_h1d

Metrics per pair (all on the pairs present in the plain run AND the arm; n is reported):
- plain CA: right in both presentation orders (strict, chance 25%). plain OI: order-invariant, a flip (orders disagree)
  counts 0.5, one parsed order decides alone.
- harness (graded) arms answer ONCE for both orders from p(A) = mean(p_ab, 1 - p_ba), so their system CA equals their
  accuracy; an exact tie (p(A) = 0.5, e.g. the same P(First) in both orders = pure position bias) counts 0.5 in both CA
  and OI (expected value of a coin). "single-call CA" = each call's own pick (P(First) > 50) right in both orders
  (paper-comparable, per call). The harness is judged on OI.
- paired deltas vs the plain run (and the first arm): mean, 10k bootstrap 95% CI, exact two-sided McNemar in sign-test
  form (pairs where the arm scores higher vs lower; identical to McNemar for 0/1 scores, and handles OI's 0.5).
- $/pair: every ledger call for the selected pairs at its model's list price (run_bench.PRICE).
- H4 abstention: commit only when |p(A) - 50| >= tau (points). Rule fixed before the runs: on dev (75) pick the tau in
  TAUS with the highest committed accuracy subject to dev coverage >= 50% (ties: smaller tau), then report held-out (177)
  coverage / committed accuracy vs the arm's forced held-out accuracy (drop rule: < forced + 3 pts at >= 50% coverage).
  Reference $0 gate: the plain run's order-consistent pairs.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_metrics import boot, ids_of, load  # noqa: E402
from run_bench import PRICE  # noqa: E402

TAUS = (0, 5, 10, 15, 20, 25, 30, 35, 40, 45)
BENCH = Path(__file__).resolve().parent


def sign_test(d: list[float]) -> tuple[int, int, float]:
    up, down = sum(x > 0 for x in d), sum(x < 0 for x in d)
    n = up + down
    if n == 0:
        return up, down, 1.0
    k = min(up, down)
    return up, down, min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def load_graded(run: Path) -> dict[int, dict]:
    out = {}
    for line in (run / "pairs.jsonl").open():
        r = json.loads(line)
        win = "A" if r["a_is_win"] else "B"
        acc = 1.0 if r["winner"] == win else 0.5 if r["winner"] == "tie" else 0.0
        pf = {j["order"]: j.get("p_first") for j in r["judgments"]}
        right = []  # per-call pick right? (P(First) > 50 names the first-shown side)
        for o in ("ab", "ba"):
            v = pf.get(o)
            first = "A" if o == "ab" else "B"
            pick = None if v is None or v == 50 else (first if v > 50 else ("B" if first == "A" else "A"))
            right.append(float(pick == win))
        out[r["index"]] = {"oi": acc, "ca": acc, "single_ca": right[0] * right[1], "p_a": r["p_a"],
                           "margin": abs(r["p_a"] - 0.5) * 100, "win": win, "source": r["source"],
                           "call_flip": float(len(set(pf.values())) > 0 and None not in pf.values()
                                              and ((pf["ab"] > 50) == (pf["ba"] > 50)) and pf["ab"] != 50),
                           "unparsed": sum(v is None for v in pf.values()) + (2 - len(pf))}
    return out


def cost(run: Path, ids: set[int]) -> float:
    c = 0.0
    for line in (run / "calls.jsonl").open():
        r = json.loads(line)
        try:
            i = int(r["key"].split("|")[0])
        except ValueError:
            continue
        if i in ids and not r.get("copied_from"):
            pin, pout = PRICE.get(r.get("model") or "", PRICE["gemini-2.5-flash"])
            c += r["tokens_in"] * pin * 1e-6 + r["tokens_out"] * pout * 1e-6
    return c


def curve(g: dict[int, dict], ids: list[int]) -> list[dict]:
    rows = []
    for t in TAUS:
        com = [i for i in ids if g[i]["margin"] >= t]  # tau 0 = forced (ties included at 0.5)
        acc = sum(g[i]["oi"] for i in com) / len(com) if com else float("nan")
        rows.append({"tau": t, "coverage": len(com) / max(1, len(ids)), "n": len(com), "acc": acc})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--indices", default="@" + str(BENCH / "fullset" / "final_indices_main.txt"))
    ap.add_argument("--dev", default="@" + str(BENCH / "dev_indices.txt"))
    ap.add_argument("--md", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    main_ids, dev = ids_of(a.indices), set(ids_of(a.dev))
    pct = lambda x: f"{100 * x:.1f}"  # noqa: E731
    sgn = lambda x: f"{100 * x:+.1f}"  # noqa: E731
    lines = ["| model | arm | n | CA | single-call CA | OI | dOI vs plain [95% CI] | McNemar p (up/down) | "
             "dCA vs plain [95% CI] | p | flip-pair acc (n) | ties | per-call flip rate | unparsed | $/pair |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    ab_lines = ["| model | arm | tau (dev) | dev cov / acc | held-out cov / committed acc | held-out forced acc | "
                "committed - forced | plain order-consistent gate, held-out cov / acc | plain OI held-out |",
                "|---|---|---|---|---|---|---|---|---|"]
    curves_md: list[str] = []
    rep: dict = {}
    for spec in a.specs:
        parts = [p.split("=", 1) for p in spec.split(",")]
        model, plain_dir = parts[0][0], Path(parts[0][1])
        plain = load(plain_dir)
        arms = [(k, Path(v), load_graded(Path(v))) for k, v in parts[1:]]
        common = [i for i in main_ids if i in plain and all(i in g for _, _, g in arms)]
        cs = set(common)
        rep[model] = {"n": len(common), "arms": {}}
        pl_oi = [plain[i]["oi"] for i in common]
        pl_ca = [plain[i]["ca"] for i in common]
        flips = [i for i in common if plain[i]["fa"] != plain[i]["sa"]]
        pc = cost(plain_dir, cs) / len(common)
        lines.append(f"| {model} | plain | {len(common)} | {pct(sum(pl_ca) / len(common))} | {pct(sum(pl_ca) / len(common))} | "
                     f"{pct(sum(pl_oi) / len(common))} | (reference) | | | | {pct(sum(plain[i]['oi'] for i in flips) / max(1, len(flips)))} ({len(flips)}) | "
                     f"| {pct(len(flips) / len(common))} | | {pc:.4f} |")
        rep[model]["plain"] = {"ca": sum(pl_ca) / len(common), "oi": sum(pl_oi) / len(common), "usd_per_pair": pc,
                               "flips": len(flips)}
        first_arm = None
        for name, d, g in arms:
            oi = [g[i]["oi"] for i in common]
            doi = [x - y for x, y in zip(oi, pl_oi)]
            dca = [g[i]["ca"] - y for i, y in zip(common, pl_ca)]
            lo, hi = boot(doi, seed=1)
            clo, chi = boot(dca, seed=2)
            up, dn, p = sign_test(doi)
            cup, cdn, cp = sign_test(dca)
            fl = sum(g[i]["oi"] for i in flips) / max(1, len(flips))
            ties = sum(g[i]["p_a"] == 0.5 for i in common)
            unp = sum(g[i]["unparsed"] for i in common)
            usd = cost(d, cs) / len(common)
            row = {"ca": sum(g[i]["ca"] for i in common) / len(common),
                   "single_ca": sum(g[i]["single_ca"] for i in common) / len(common), "oi": sum(oi) / len(common),
                   "doi": sum(doi) / len(common), "doi_ci": (lo, hi), "doi_p": p, "doi_up_down": (up, dn),
                   "dca": sum(dca) / len(common), "dca_ci": (clo, chi), "dca_p": cp, "flip_pair_acc": fl,
                   "ties": ties, "unparsed": unp, "usd_per_pair": usd, "call_flip_rate":
                   sum(g[i]["call_flip"] for i in common) / len(common)}
            if first_arm is not None:
                base = [first_arm[i]["oi"] for i in common]
                dd = [x - y for x, y in zip(oi, base)]
                row["doi_vs_first_arm"] = sum(dd) / len(dd)
                row["doi_vs_first_arm_ci"] = boot(dd, seed=3)
                row["doi_vs_first_arm_p"] = sign_test(dd)[2]
            lines.append(f"| {model} | {name} | {len(common)} | {pct(row['ca'])} | {pct(row['single_ca'])} | {pct(row['oi'])} | "
                         f"{sgn(row['doi'])} [{sgn(lo)}, {sgn(hi)}] | {p:.2g} ({up}/{dn}) | {sgn(row['dca'])} [{sgn(clo)}, {sgn(chi)}] | "
                         f"{cp:.2g} | {pct(fl)} ({len(flips)}) | {ties} | {pct(row['call_flip_rate'])} | {unp} | {usd:.4f} |")
            # H4
            dv = [i for i in common if i in dev]
            ho = [i for i in common if i not in dev]
            cdev, cho, call_ = curve(g, dv), curve(g, ho), curve(g, common)
            ok = [r for r in cdev if r["coverage"] >= 0.5 and r["n"] > 0]
            best = max(ok, key=lambda r: (round(r["acc"], 9), -r["tau"])) if ok else cdev[0]
            h = next(r for r in cho if r["tau"] == best["tau"])
            forced = sum(g[i]["oi"] for i in ho) / len(ho)
            cons = [i for i in ho if plain[i]["fa"] == plain[i]["sa"]]
            cons_acc = sum(plain[i]["fa"] for i in cons) / max(1, len(cons))
            pl_ho = sum(plain[i]["oi"] for i in ho) / len(ho)
            ab_lines.append(f"| {model} | {name} | {best['tau']} | {pct(best['coverage'])}% / {pct(best['acc'])} | "
                            f"{pct(h['coverage'])}% ({h['n']}/{len(ho)}) / {pct(h['acc'])} | {pct(forced)} | "
                            f"{sgn(h['acc'] - forced)} | {pct(len(cons) / len(ho))}% / {pct(cons_acc)} | {pct(pl_ho)} |")
            curves_md.append(f"\n**{model} {name}** (n dev {len(dv)}, held-out {len(ho)}): tau -> coverage / committed acc\n\n"
                             "| tau | dev | held-out | all |\n|---|---|---|---|\n" + "\n".join(
                                 f"| {r1['tau']} | {pct(r1['coverage'])}% / {pct(r1['acc']) if r1['n'] else '-'} | "
                                 f"{pct(r2['coverage'])}% / {pct(r2['acc']) if r2['n'] else '-'} | "
                                 f"{pct(r3['coverage'])}% / {pct(r3['acc']) if r3['n'] else '-'} |"
                                 for r1, r2, r3 in zip(cdev, cho, call_)))
            row["h4"] = {"tau": best["tau"], "dev": best, "heldout": h, "heldout_forced": forced,
                         "plain_consistent_heldout": {"coverage": len(cons) / len(ho), "acc": cons_acc},
                         "curves": {"dev": cdev, "heldout": cho, "all": call_}}
            rep[model]["arms"][name] = row
            first_arm = first_arm or g
    text = "\n".join(lines) + "\n\nH4 abstention (tau fixed on dev, checked on held-out):\n\n" + "\n".join(ab_lines) + \
        "\n" + "\n".join(curves_md)
    print(text)
    if a.md:
        Path(a.md).write_text(text + "\n")
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
