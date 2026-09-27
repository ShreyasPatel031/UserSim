#!/usr/bin/env python3
"""Markdown summary for one or more run dirs: headline table, by source, cost, example misses."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
DATA = Path("/workspace/bench/wiserui/repo/WiserUI_Bench.json")


def pct(x):
    return f"{100 * x:.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="label=run_dir")
    ap.add_argument("--indices", default="")
    ap.add_argument("--misses", type=int, default=3)
    args = ap.parse_args()
    meta = {x["index"]: x for x in json.load(open(DATA))}
    out = []
    for spec in args.runs:
        label, run = spec.split("=", 1)
        cmd = [sys.executable, str(HERE / "score.py"), run] + (["--indices", args.indices] if args.indices else [])
        rep = json.loads(subprocess.check_output(cmd))
        Path(run, "scores.json").write_text(json.dumps(rep, indent=1))
        calls = [json.loads(l) for l in open(Path(run) / "calls.jsonl")]
        cost = sum(c.get("cost_usd", 0) for c in calls)
        out.append(f"\n## {label} ({run})\n")
        out.append(f"Model calls: {len(calls)}, spend ${cost:.2f} (tokens in {sum(c['tokens_in'] for c in calls):,}, out {sum(c['tokens_out'] for c in calls):,}); call errors {sum(1 for c in calls if c.get('error'))}\n")
        out.append("| condition | group | N | consistent acc [95% CI] | plain acc [95% CI] | 1st-pos pick | 2nd-pos pick | acc win-1st / win-2nd | unresolved | extras |")
        out.append("|---|---|---|---|---|---|---|---|---|---|")
        for cond, groups in sorted(rep.items()):
            for g in ["all", "vwo", "goodui", "abtest", "web", "mobile"]:
                m = groups.get(g)
                if not m or not m.get("n"):
                    continue
                extra = ""
                if "pooled_12vote_acc" in m:
                    extra = (f"12-vote pooled {pct(m['pooled_12vote_acc'])}; persona votes right {pct(m['persona_vote_correct_rate'])}, "
                             f"1st {pct(m['persona_vote_first_rate'])}; 3-3 ties {m['vote_ties']}; unresolved-as-half AA {pct(m['plain_acc_unresolved_as_half'])}")
                out.append(f"| {cond} | {g} | {m['n']} | {pct(m['consistent_acc'])} [{pct(m['ca_ci95'][0])}, {pct(m['ca_ci95'][1])}] | "
                           f"{pct(m['plain_acc'])} [{pct(m['aa_ci95'][0])}, {pct(m['aa_ci95'][1])}] | {pct(m['first_pick_rate'])} | "
                           f"{pct(m['second_pick_rate'])} | {pct(m['acc_when_winner_first'])} / {pct(m['acc_when_winner_second'])} | {m['unparsed_or_tie']} | {extra} |")
        # misses: usersim pairs wrong in both orders, with persona reasons
        rows = [json.loads(l) for l in open(Path(run) / "judgments.jsonl")]
        us = {}
        for r in rows:
            if r["condition"] == "usersim":
                us.setdefault(r["index"], {})[r["order"]] = r
        bl = {}
        for r in rows:
            if r["condition"] == "baseline":
                bl.setdefault(r["index"], {})[r["order"]] = r
        missed = [i for i, p in us.items() if len(p) == 2 and p["wl"]["pick"] == "Second" and p["lw"]["pick"] == "First"]
        out.append(f"\nUserSim pairs where the loser won the vote in both orders: {len(missed)}\n")
        for i in sorted(missed, key=lambda i: -(us[i]["wl"]["n_second"] + us[i]["lw"]["n_first"]))[: args.misses]:
            m = meta[i]
            p = us[i]
            reasons = [v["reason"] for v in p["wl"]["votes"] if v["choice"] == "Second"][:2]
            b = bl.get(i, {})
            out.append(f"- #{i} {m['company']} {m['page_type']} ({m['source']}); changed: {json.dumps(m['ui_change'])}. "
                       f"Votes for the loser: {p['wl']['n_second']}/6 with the winner shown first, {p['lw']['n_first']}/6 with it shown second. "
                       f"Baseline picks (winner 1st / 2nd): {b.get('wl', {}).get('pick')} / {b.get('lw', {}).get('pick')}. "
                       f"Why the winner won, per the benchmark: \"{m['rationale'][0]['reason']}\". Persona reasons for the loser: "
                       + " | ".join(f"\"{r}\"" for r in reasons))
    print("\n".join(out))


if __name__ == "__main__":
    main()
