#!/usr/bin/env python3
"""Export G-FOCUS runs as per-order examples for a later "final pick + brief reasoning" fine-tune.

usage: export_ft.py label=results/run_dir ... --out ft_examples.jsonl [--indices @file]

One JSON line per (pair, presentation order), everything needed to rebuild a training example:
  arm, index, order ("ab": version A shown first), images.first / images.second (paths; crops are recomputable
  with mvp.pairwise.diff_regions), ctx (company, page type, industry, platform, plus change when that input was on),
  inputs (the goal and key differences this order's stages used, and the "Additional information" block),
  gold ("First"/"Second": the A/B winner's position in this order), pick, correct,
  brief_reasoning (the Evaluator's Key Rationale), importance_ranking, reasons_first / reasons_second, evaluator_raw.
Train only on held-in data: the WiserUI pairs are the eval set (and CC BY-NC-SA), so these rows are for building and
checking the format, and for distillation experiments on non-WiserUI pairs produced the same way.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def ids_of(arg: str) -> set[int]:
    raw = Path(arg[1:]).read_text() if arg.startswith("@") else arg
    return {int(x) for x in raw.replace("\n", ",").split(",") if x.strip()}


def section(text: str, head: str) -> str:
    t = (text or "").replace("**", "")
    m = re.search(r"\[\s*" + re.escape(head) + r"\s*\]\s*:?", t, re.I)
    if not m:
        return ""
    rest = t[m.end():]
    n = re.search(r"\n\s*\[[A-Z][^\]\n]{2,40}\]", rest)
    return (rest[: n.start()] if n else rest).strip()


def brief(evaluator: str) -> str:
    concl = section(evaluator, "Conclusion")
    m = re.search(r"Key Rationale\s*:?(.*)", concl, re.S | re.I)
    return " ".join((m.group(1) if m else concl).split())[:1200]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--indices", default="")
    args = ap.parse_args()
    keep = ids_of(args.indices) if args.indices else None
    n = 0
    with open(args.out, "w") as f:
        for spec in args.runs:
            arm, path = spec.split("=", 1)
            cfg = json.loads((Path(path) / "config.json").read_text())
            for line in (Path(path) / "pairs.jsonl").open():
                r = json.loads(line)
                if keep is not None and r["index"] not in keep:
                    continue
                win = "A" if r["a_is_win"] else "B"
                imgs = r.get("images") or {}
                for j in r["judgments"]:
                    o = j["order"]
                    first, second = ("a", "b") if o == "ab" else ("b", "a")
                    gd = (r.get("goal_diffs_by_order") or {}).get(o) or {}
                    gold = "First" if (o == "ab") == (win == "A") else "Second"
                    f.write(json.dumps({
                        "arm": arm, "inputs_flags": cfg.get("inputs", []), "index": r["index"], "order": o,
                        "source": r.get("source"), "images": {"first": imgs.get(first), "second": imgs.get(second)},
                        "ctx": r.get("ctx"),
                        "inputs": {"goal": gd.get("goal"), "key_differences": gd.get("diffs_text"),
                                   "additional_information": gd.get("extra_text", "")},
                        "gold": gold, "pick": j.get("pick"), "correct": j.get("pick") == gold,
                        "brief_reasoning": brief(j.get("evaluator", "")),
                        "importance_ranking": " ".join(section(j.get("evaluator", ""), "Importance Ranking").split())[:1500],
                        "reasons_first": j.get("reasons_first"), "reasons_second": j.get("reasons_second"),
                        "evaluator_raw": j.get("evaluator"),
                    }, ensure_ascii=False) + "\n")
                    n += 1
    print(f"[export_ft] {n} rows -> {args.out}")


if __name__ == "__main__":
    main()
