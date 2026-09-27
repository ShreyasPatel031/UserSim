#!/usr/bin/env python3
"""Ablation table for the pairwise streams vs the old UserSim vote (A0).

usage: ablate.py --indices @dev_indices.txt A0=results/full S1=results/pw_s1 S2=... [--pairs S1:A0,S2:S1]

Per pair (both presentation orders):
  CA   right in both orders (paper metric, chance 25%); FA / SA = accuracy when the winner is shown first / second
  OI   order-invariant accuracy: one pick per pair from both orders together (pw: p(A>B) from ratings averaged
       across orders; A0: its 12 pooled votes); a tie counts 0.5. Chance 50%.
  first-slot pick rate and tie rate over per-order picks (ties count wrong in CA/FA/SA)
  agreement: share of personas on the majority side per order; persona order-consistency: share of personas that
       prefer the same version in both orders
  calls and $ per pair from calls.jsonl
Paired bootstrap (10k, pair-level) for CA and OI differences.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

B = 10000


def load_a0(run: Path, keep: set[int]) -> dict[int, dict]:
    rows = [json.loads(l) for l in (run / "judgments.jsonl").open()]
    by: dict[int, dict] = defaultdict(dict)
    for r in rows:
        if r["condition"] == "usersim" and r["index"] in keep:
            by[r["index"]][r["order"]] = r
    cost: dict[int, list] = defaultdict(lambda: [0, 0.0])
    for l in (run / "calls.jsonl").open():
        c = json.loads(l)
        p = c["key"].split("|")
        if p[0] == "usersim" and int(p[1]) in keep:
            cost[int(p[1])][0] += 1
            cost[int(p[1])][1] += c.get("cost_usd", 0.0)
    out = {}
    for i, o in by.items():
        wl, lw = o["wl"], o["lw"]
        win_v = sum(v["choice"] == "First" for v in wl["votes"]) + sum(v["choice"] == "Second" for v in lw["votes"])
        lose_v = sum(v["choice"] == "Second" for v in wl["votes"]) + sum(v["choice"] == "First" for v in lw["votes"])
        agree = []
        for r in (wl, lw):
            vs = [v["choice"] for v in r["votes"]]
            agree.append(max(vs.count("First"), vs.count("Second")) / max(1, len(vs)))
        kv = {v["k"]: v["choice"] for v in wl["votes"]}
        cons = [(kv.get(v["k"]) == "First") == (v["choice"] == "Second") and v["choice"] in ("First", "Second")
                and kv.get(v["k"]) in ("First", "Second") for v in lw["votes"]]
        out[i] = {"source": wl["source"], "wl": wl["pick"], "lw": lw["pick"],
                  "oi": 1.0 if win_v > lose_v else 0.5 if win_v == lose_v else 0.0,
                  "agree": sum(agree) / 2, "cons": sum(cons) / max(1, len(cons)),
                  "calls": cost[i][0], "usd": cost[i][1]}
    return out


def load_pw(run: Path, keep: set[int]) -> dict[int, dict]:
    cost: dict[int, list] = defaultdict(lambda: [0, 0.0])
    for l in (run / "calls.jsonl").open():
        c = json.loads(l)
        i = int(c["key"].split("|")[0])
        cost[i][0] += 1
        cost[i][1] += c.get("cost_usd", 0.0)
    out = {}
    for l in (run / "pairs.jsonl").open():
        r = json.loads(l)
        i = r["index"]
        if i not in keep:
            continue
        win = "A" if r["a_is_win"] else "B"
        picks = {}
        agree = []
        for o, ov in r["orders"].items():
            winner_first = (o == "ab") == (win == "A")
            picks["wl" if winner_first else "lw"] = {"X": "First", "Y": "Second"}.get(ov["pick"], "tie")
            n = sum(1 for j in r["judgments"] if j["order"] == o and j["ok"])
            agree.append(max(ov["n_x"], ov["n_y"]) / max(1, n))
        cons = [(p["by_order"].get("ab", 0) > 0 and p["by_order"].get("ba", 0) > 0)
                or (p["by_order"].get("ab", 0) < 0 and p["by_order"].get("ba", 0) < 0)
                for p in r["personas"] if len(p["by_order"]) == 2]
        out[i] = {"source": r["source"], "wl": picks.get("wl", "tie"), "lw": picks.get("lw", "tie"),
                  "oi": 1.0 if r["winner"] == win else 0.5 if r["winner"] == "tie" else 0.0,
                  "agree": sum(agree) / max(1, len(agree)), "cons": sum(cons) / max(1, len(cons)),
                  "calls": cost[i][0], "usd": cost[i][1], "p_win": r["p_a"] if win == "A" else 1 - r["p_a"]}
    return out


def per_pair(x: dict) -> dict:
    fa = float(x["wl"] == "First")
    sa = float(x["lw"] == "Second")
    return {"ca": fa * sa, "fa": fa, "sa": sa, "oi": x["oi"],
            "first": ((x["wl"] == "First") + (x["lw"] == "First")) / 2,
            "tie": ((x["wl"] == "tie") + (x["lw"] == "tie")) / 2,
            "agree": x["agree"], "cons": x["cons"], "calls": x["calls"], "usd": x["usd"]}


def ci(vals: list[float], seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(vals)
    bs = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return bs[int(0.025 * B)], bs[int(0.975 * B) - 1]


def summarize(sys: dict[int, dict], ids: list[int]) -> dict:
    pp = [per_pair(sys[i]) for i in ids]
    out = {"n": len(ids)}
    for k in pp[0]:
        out[k] = sum(p[k] for p in pp) / len(pp)
    out["ca_ci"] = ci([p["ca"] for p in pp])
    out["oi_ci"] = ci([p["oi"] for p in pp])
    for src in sorted({sys[i]["source"] for i in ids}):
        sub = [per_pair(sys[i]) for i in ids if sys[i]["source"] == src]
        out[f"ca_{src}"] = sum(p["ca"] for p in sub) / len(sub)
        out[f"oi_{src}"] = sum(p["oi"] for p in sub) / len(sub)
        out[f"n_{src}"] = len(sub)
    return out


def paired(a: dict, b: dict, ids: list[int]) -> dict:
    res = {}
    for k in ("ca", "oi"):
        d = [per_pair(b[i])[k] - per_pair(a[i])[k] for i in ids]
        res[k] = (sum(d) / len(d), *ci(d, seed=1))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("systems", nargs="+", help="LABEL=run_dir; a label starting with A0 uses the old usersim format")
    ap.add_argument("--indices", required=True)
    ap.add_argument("--pairs", default="", help="comma list of B:A for paired bootstrap B - A")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    raw = Path(args.indices[1:]).read_text() if args.indices.startswith("@") else args.indices
    keep = {int(x) for x in raw.replace("\n", ",").split(",") if x.strip()}
    systems = {}
    for s in args.systems:
        label, path = s.split("=", 1)
        systems[label] = (load_a0 if label.startswith("A0") else load_pw)(Path(path), keep)
    ids = sorted(set.intersection(*(set(v) for v in systems.values())))
    summ = {k: summarize(v, ids) for k, v in systems.items()}
    pct = lambda x: f"{100 * x:.1f}"  # noqa: E731
    srcs = sorted({k[3:] for s in summ.values() for k in s if k.startswith("ca_") and k != "ca_ci"})
    print(f"n = {len(ids)} shared pairs\n")
    print("| arm | CA [95% CI] | FA / SA | OI [95% CI] | 1st-slot / tie | persona agree / order-consistent | calls, $ per pair | "
          + " | ".join(f"{s} CA / OI (n={summ[next(iter(summ))].get('n_' + s)})" for s in srcs) + " |")
    print("|---|---|---|---|---|---|---|" + "---|" * len(srcs))
    for k, s in summ.items():
        print(f"| {k} | {pct(s['ca'])} [{pct(s['ca_ci'][0])}, {pct(s['ca_ci'][1])}] | {pct(s['fa'])} / {pct(s['sa'])} | "
              f"{pct(s['oi'])} [{pct(s['oi_ci'][0])}, {pct(s['oi_ci'][1])}] | {pct(s['first'])} / {pct(s['tie'])} | "
              f"{pct(s['agree'])} / {pct(s['cons'])} | {s['calls']:.1f}, ${s['usd']:.4f} | "
              + " | ".join(f"{pct(s['ca_' + x])} / {pct(s['oi_' + x])}" for x in srcs) + " |")
    pairs_out = {}
    if args.pairs:
        print("\n| comparison | dCA [95% CI] | dOI [95% CI] |\n|---|---|---|")
        for pr in args.pairs.split(","):
            b, a = pr.split(":")
            d = paired(systems[a], systems[b], ids)
            pairs_out[pr] = d
            print(f"| {b} - {a} | {100 * d['ca'][0]:+.1f} [{100 * d['ca'][1]:+.1f}, {100 * d['ca'][2]:+.1f}] | "
                  f"{100 * d['oi'][0]:+.1f} [{100 * d['oi'][1]:+.1f}, {100 * d['oi'][2]:+.1f}] |")
    if args.json:
        Path(args.json).write_text(json.dumps({"n": len(ids), "summary": summ, "paired": pairs_out}, indent=1))


if __name__ == "__main__":
    main()
