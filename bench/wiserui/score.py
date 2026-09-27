#!/usr/bin/env python3
"""Score judgments.jsonl: consistent accuracy (CA), plain accuracy (AA), position bias, by source.

CA (paper): a pair counts only if the winner is picked in BOTH orders. Chance = 25%.
AA: mean correctness over both orders. Chance = 50%. 95% CI = pair-level bootstrap (10k).
Pooled: one prediction per pair from both orders together (usersim: 12 votes; baseline: agree -> that pick,
disagree -> counted wrong); an order-debiased single-pick accuracy, chance 50%.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path


def correct(r: dict) -> int:
    # order wl = winner first; lw = winner second
    want = "First" if r["order"] == "wl" else "Second"
    return int(r["pick"] == want)


def picked_first(r: dict) -> int:
    return int(r["pick"] == "First")


def metrics(pairs: dict[int, dict[str, dict]]) -> dict:
    ids = [i for i, p in pairs.items() if "wl" in p and "lw" in p]
    n = len(ids)
    if not n:
        return {"n": 0}
    ca = [correct(pairs[i]["wl"]) * correct(pairs[i]["lw"]) for i in ids]
    aa = [(correct(pairs[i]["wl"]) + correct(pairs[i]["lw"])) / 2 for i in ids]
    def soft(r: dict) -> float:
        return 0.5 if r["pick"] not in ("First", "Second") else float(correct(r))
    aa_soft = [(soft(pairs[i]["wl"]) + soft(pairs[i]["lw"])) / 2 for i in ids]
    first = [(picked_first(pairs[i]["wl"]) + picked_first(pairs[i]["lw"])) / 2 for i in ids]
    unparsed = sum(pairs[i][o]["pick"] not in ("First", "Second") for i in ids for o in ("wl", "lw"))
    pooled = []
    for i in ids:
        a, b = pairs[i]["wl"], pairs[i]["lw"]
        if a.get("votes") is not None:
            win_votes = sum(v["choice"] == "First" for v in a["votes"]) + sum(v["choice"] == "Second" for v in b["votes"])
            lose_votes = sum(v["choice"] == "Second" for v in a["votes"]) + sum(v["choice"] == "First" for v in b["votes"])
            pooled.append(1.0 if win_votes > lose_votes else 0.5 if win_votes == lose_votes else 0.0)
        else:
            # single call per order: pooling the two orders is exactly AA (agree-right 1, split 0.5, agree-wrong 0)
            pooled.append((correct(a) + correct(b)) / 2)
    rng = random.Random(0)
    boots_aa, boots_ca = [], []
    for _ in range(10000):
        s = [rng.randrange(n) for _ in range(n)]
        boots_aa.append(sum(aa[k] for k in s) / n)
        boots_ca.append(sum(ca[k] for k in s) / n)
    boots_aa.sort(); boots_ca.sort()
    lo, hi = int(0.025 * 10000), int(0.975 * 10000) - 1
    out = {
        "n": n,
        "consistent_acc": sum(ca) / n, "ca_ci95": [boots_ca[lo], boots_ca[hi]],
        "plain_acc": sum(aa) / n, "aa_ci95": [boots_aa[lo], boots_aa[hi]],
        "plain_acc_unresolved_as_half": sum(aa_soft) / n,
        "first_pick_rate": sum(first) / n, "second_pick_rate": 1 - sum(first) / n - unparsed / (2 * n),
        "acc_when_winner_first": sum(correct(pairs[i]["wl"]) for i in ids) / n,
        "acc_when_winner_second": sum(correct(pairs[i]["lw"]) for i in ids) / n,
        "unparsed_or_tie": unparsed,
    }
    if pairs[ids[0]]["wl"].get("votes") is not None:
        out["pooled_12vote_acc"] = sum(pooled) / n
        out["vote_ties"] = sum(pairs[i][o].get("tie_vote", False) for i in ids for o in ("wl", "lw"))
        allv = [v for i in ids for o in ("wl", "lw") for v in pairs[i][o]["votes"]]
        out["persona_votes"] = len(allv)
        out["persona_vote_first_rate"] = sum(v["choice"] == "First" for v in allv) / max(1, len(allv))
        out["persona_vote_correct_rate"] = sum(
            (v["choice"] == ("First" if o == "wl" else "Second")) for i in ids for o in ("wl", "lw") for v in pairs[i][o]["votes"]
        ) / max(1, len(allv))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--indices", default="", help="restrict to comma list or @file")
    args = ap.parse_args()
    run = Path(args.run_dir)
    rows = [json.loads(l) for l in (run / "judgments.jsonl").open()]
    keep = None
    if args.indices:
        raw = Path(args.indices[1:]).read_text() if args.indices.startswith("@") else args.indices
        keep = {int(x) for x in raw.split(",") if x.strip()}
    by: dict[str, dict[str, dict[int, dict[str, dict]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for r in rows:
        if keep is not None and r["index"] not in keep:
            continue
        for grp in ("all", r["source"], r["web_mobile"]):
            by[r["condition"]][grp][r["index"]][r["order"]] = r
    report = {c: {g: metrics(p) for g, p in groups.items()} for c, groups in by.items()}
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
