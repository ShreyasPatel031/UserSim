#!/usr/bin/env python3
"""Offline ROI router / cascade simulation from saved judgments ($0; HARNESS_CHEAP_REPORT.md section "Router").

Each stage is one model's saved run on the 252 pairs:
- graded (H1 harness): answer = sign(p(A) - 0.5); confident if |p(A) - 50| >= tau (points);
- plain (vanilla, both orders): answer = the pick when both orders agree (confident); a flip is not confident.
A cascade runs stage 1 on every pair, escalates the not-confident pairs to stage 2, and so on; the last stage always
answers (a plain flip / graded tie = 0.5, a coin). Accuracy is order-invariant (= OI = system CA). Cost per pair = the
actual metered cost of every stage the pair visited (tokens x list price from each ledger).

Outputs: every cascade's (accuracy, $/pair) on all 252 (in-sample), the Pareto frontier, and an honest version: for
each $/pair budget the cascade + taus picked on DEV (75) under that budget, scored on HELD-OUT (177).
usage: router_sim.py [--md out.md] [--json out.json] [--png out.png]
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_metrics import ids_of, load  # noqa: E402
from run_bench import PRICE  # noqa: E402

BENCH = Path(__file__).resolve().parent
RES = Path("/workspace/bench/wiserui/results")
# name -> (run dir, kind)
SYSTEMS = {
    "luna_h1": ("hc_luna_h1", "graded"), "flash_h1": ("hc_flash_h1", "graded"),
    "luna": ("van_gpt6luna", "plain"), "flash": ("van_g38flash", "plain"), "sol": ("van_gpt6sol", "plain"),
    "sonnet5": ("van_sonnet5", "plain"), "pro": ("van_g31pro", "plain"), "opus": ("van_opus55", "plain"),
}
TAUS = (5, 10, 15, 20, 25, 30, 35)
BUDGETS = (0.001, 0.002, 0.004, 0.008, 0.012, 0.02, 0.03, 0.06)


def pair_costs(run: Path) -> dict[int, float]:
    c: dict[int, float] = {}
    for line in (run / "calls.jsonl").open():
        r = json.loads(line)
        try:
            i = int(r["key"].split("|")[0])
        except ValueError:
            continue
        pin, pout = PRICE.get(r.get("model") or "", PRICE["gemini-2.5-flash"])
        c[i] = c.get(i, 0.0) + r["tokens_in"] * pin * 1e-6 + r["tokens_out"] * pout * 1e-6
    return c


def load_system(name: str) -> dict[int, dict]:
    d, kind = SYSTEMS[name]
    run = RES / d
    cost = pair_costs(run)
    out = {}
    if kind == "plain":
        for i, v in load(run).items():
            cons = v["fa"] == v["sa"]
            out[i] = {"acc": v["fa"] if cons else 0.5, "margin": 50.0 if cons else 0.0, "cost": cost.get(i, 0.0)}
    else:
        for line in (run / "pairs.jsonl").open():
            r = json.loads(line)
            win = "A" if r["a_is_win"] else "B"
            acc = 1.0 if r["winner"] == win else 0.5 if r["winner"] == "tie" else 0.0
            out[r["index"]] = {"acc": acc, "margin": abs(r["p_a"] - 0.5) * 100, "cost": cost.get(r["index"], 0.0)}
    return out


def run_cascade(S: dict, chain: tuple, taus: tuple, ids: list[int]) -> tuple[float, float, list[float]]:
    acc = cost = 0.0
    frac = [0.0] * len(chain)
    for i in ids:
        for k, (name, tau) in enumerate(zip(chain, taus)):
            s = S[name][i]
            cost += s["cost"]
            frac[k] += 1
            last = k == len(chain) - 1
            thr = 50.0 if SYSTEMS[name][1] == "plain" else tau
            if last or s["margin"] >= thr - 1e-9:
                acc += s["acc"]
                break
    n = len(ids)
    return acc / n, cost / n, [f / n for f in frac]


def configs(names: list[str]):
    order = sorted(names, key=lambda x: MEAN_COST[x])
    for L in (1, 2, 3):
        for chain in itertools.combinations(order, L):
            grids = [TAUS if (SYSTEMS[c][1] == "graded" and k < L - 1) else (0,) for k, c in enumerate(chain)]
            for taus in itertools.product(*grids):
                yield chain, taus


MEAN_COST: dict[str, float] = {}


def label(chain, taus) -> str:
    return " -> ".join(f"{c}" + (f"(tau{t})" if t and SYSTEMS[c][1] == "graded" else "") for c, t in zip(chain, taus))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--png", default="")
    a = ap.parse_args()
    main_ids = ids_of("@" + str(BENCH / "fullset" / "final_indices_main.txt"))
    dev = set(ids_of("@" + str(BENCH / "dev_indices.txt")))
    S = {n: load_system(n) for n in SYSTEMS}
    ids = [i for i in main_ids if all(i in S[n] for n in S)]
    dv, ho = [i for i in ids if i in dev], [i for i in ids if i not in dev]
    for n in S:
        MEAN_COST[n] = sum(S[n][i]["cost"] for i in ids) / len(ids)
    rows = []
    for chain, taus in configs(list(S)):
        acc, cost, frac = run_cascade(S, chain, taus, ids)
        dacc, dcost, _ = run_cascade(S, chain, taus, dv)
        hacc, hcost, _ = run_cascade(S, chain, taus, ho)
        rows.append({"chain": chain, "taus": taus, "label": label(chain, taus), "acc": acc, "cost": cost,
                     "reach": frac, "dev_acc": dacc, "dev_cost": dcost, "ho_acc": hacc, "ho_cost": hcost})
    singles = [r for r in rows if len(r["chain"]) == 1]
    front, best = [], -1.0
    for r in sorted(rows, key=lambda r: (r["cost"], -r["acc"])):
        if r["acc"] > best + 1e-9:
            front.append(r)
            best = r["acc"]
    pct = lambda x: f"{100 * x:.1f}"  # noqa: E731
    L = [f"n = {len(ids)} pairs (dev {len(dv)}, held-out {len(ho)}); {len(rows)} cascades", "",
         "Single systems (order-invariant accuracy = OI):", "",
         "| system | acc all | acc held-out | $/pair |", "|---|---|---|---|"]
    for r in sorted(singles, key=lambda r: r["cost"]):
        L.append(f"| {r['label']} | {pct(r['acc'])} | {pct(r['ho_acc'])} | {r['cost']:.4f} |")
    L += ["", "In-sample Pareto frontier (all 252; taus chosen on the same pairs, optimistic):", "",
          "| cascade | acc all | $/pair | share reaching each stage |", "|---|---|---|---|"]
    for r in front:
        L.append(f"| {r['label']} | {pct(r['acc'])} | {r['cost']:.4f} | {' / '.join(pct(f) for f in r['reach'])} |")
    L += ["", "Honest: cascade + taus picked on dev (max dev acc with dev $/pair <= budget), scored on held-out; vs the best "
          "single system under the same budget picked the same way:", "",
          "| budget $/pair | picked on dev | dev acc | held-out acc | held-out $/pair | best single (dev-picked) | its held-out acc | its $/pair |",
          "|---|---|---|---|---|---|---|---|"]
    honest = []
    for B in BUDGETS:
        ok = [r for r in rows if r["dev_cost"] <= B]
        oks = [r for r in singles if r["dev_cost"] <= B]
        if not ok:
            continue
        p = max(ok, key=lambda r: (r["dev_acc"], -r["dev_cost"]))
        s = max(oks, key=lambda r: (r["dev_acc"], -r["dev_cost"])) if oks else None
        honest.append({"budget": B, "picked": p["label"], "dev_acc": p["dev_acc"], "ho_acc": p["ho_acc"],
                       "ho_cost": p["ho_cost"], "single": s and s["label"], "single_ho_acc": s and s["ho_acc"],
                       "single_ho_cost": s and s["ho_cost"]})
        L.append(f"| {B:.3f} | {p['label']} | {pct(p['dev_acc'])} | {pct(p['ho_acc'])} | {p['ho_cost']:.4f} | "
                 f"{s['label'] if s else '-'} | {pct(s['ho_acc']) if s else '-'} | {s['ho_cost']:.4f} |" if s else "")
    text = "\n".join(L)
    print(text)
    if a.md:
        Path(a.md).write_text(text + "\n")
    if a.json:
        Path(a.json).write_text(json.dumps({"front": front, "singles": singles, "honest": honest}, indent=1, default=list))
    if a.png:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 6))
        ax.scatter([r["cost"] for r in rows], [100 * r["acc"] for r in rows], s=6, c="#bbbbbb", label="all cascades")
        ax.plot([r["cost"] for r in front], [100 * r["acc"] for r in front], "-o", c="#d62728", ms=4,
                label="in-sample frontier (252)")
        ax.scatter([r["cost"] for r in singles], [100 * r["acc"] for r in singles], s=40, c="#1f77b4", zorder=3,
                   label="single systems")
        for r in singles:
            ax.annotate(r["label"], (r["cost"], 100 * r["acc"]), fontsize=8, xytext=(4, -10), textcoords="offset points")
        ax.plot([h["ho_cost"] for h in honest], [100 * h["ho_acc"] for h in honest], "--s", c="#2ca02c", ms=4,
                label="dev-picked, held-out (177)")
        ax.set_xscale("log")
        ax.set_xlabel("$ per pair (log)")
        ax.set_ylabel("order-invariant accuracy (OI, %)")
        ax.set_title("WiserUI-Bench: cascades of saved judgments, accuracy vs cost")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="lower right")
        fig.tight_layout()
        fig.savefig(a.png, dpi=120)


if __name__ == "__main__":
    main()
