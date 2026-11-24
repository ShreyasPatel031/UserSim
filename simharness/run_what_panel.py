"""WHAT-PANEL: person-built comments for a day's launches, to be scored by a launch-level theme scorer.

For every launch on a day's 00:05 line-up, pick a panel of real held people (those whose upvote history is closest to
the launch's topics, among people who have written comments before), and write the prompt each panel member's
simulated comment is generated from: their history before the day plus the launch's line-up fields.

    python -m simharness.run_what_panel build --bench BENCH --lineup LINEUP.json --day 2026-11-23 --out OUT [--panel 30]
    python -m simharness.run_what_panel pack  --gen GEN.jsonl --arm NAME --day 2026-11-23 --out OUT/NAME.json

`build` writes OUT/eval.jsonl in the fine-tune format ({"messages": [user], "meta": {day, slug, person_idx}}), which
finetune/lora.py generate (tuned or untuned open model) and any prompt model can answer. `pack` turns a generation
file into {day, arm, launches: {slug: [comments]}} for the scorer. Leak rules: history from days before `--day`;
launch fields from the 00:05 line-up only. Outputs hold simulated text built on private histories: keep them private.
"""
from __future__ import annotations

import argparse
import ast
import json
import os

import numpy as np

from simharness.bench import Benchmark, Item, scrub
from simharness.finetune.export import FT_PROMPT
from simharness.task_c import _item_fields


def lineup_items(path: str) -> list[Item]:
    out = []
    for i, r in enumerate(json.load(open(path))):
        topics = r.get("topics")
        if isinstance(topics, str):
            topics = ast.literal_eval(topics)
        names = [e["node"]["name"] for e in (topics or {}).get("edges", [])]
        out.append(Item(-1 - i, str(r["slug"]), "", scrub(str(r["name"])), scrub(str(r.get("tagline") or "")),
                        scrub(str(r.get("description") or "")), names))
    return out


def build(a) -> None:
    os.makedirs(a.out, exist_ok=True)
    bench = Benchmark(a.bench)
    st = bench.state(a.day)
    ok = np.flatnonzero((st["n60"] >= 1) & (st["n_comments"] >= a.min_comments))  # active, and has a voice to imitate
    n_rows, info = 0, {}
    with open(f"{a.out}/eval.jsonl", "w") as f:
        for item in lineup_items(a.lineup):
            vec = np.zeros(len(bench.vocab), np.float32)
            for t in item.tags:
                if t in bench.vocab:
                    vec[bench.vocab[t]] = 1.0
            share = np.asarray(st["topics"][ok] @ vec).ravel() / (np.maximum(st["n_all"][ok], 1.0) * max(vec.sum(), 1.0))
            order = np.lexsort((-st["n30"][ok], -share))  # topic share first, recent activity as the tie-break
            panel = ok[order[: a.panel]]
            batch = bench.batch(a.day, panel)
            for j, pid in enumerate(panel):
                prompt = FT_PROMPT.format(history=batch.render(j, 30, 10), **_item_fields(item))
                f.write(json.dumps({"messages": [{"role": "user", "content": prompt}],
                                    "meta": {"split": "panel", "day": a.day, "slug": item.item_id,
                                             "person_idx": int(pid), "item_idx": item.item_idx}}) + "\n")
                n_rows += 1
            info[item.item_id] = {"topics_known": int(vec.sum()), "mean_topic_share": round(float(share[order[: a.panel]].mean()), 4)}
    json.dump({"day": a.day, "launches": len(info), "rows": n_rows, "panel": a.panel, "eligible_people": int(len(ok)),
               "per_launch": info}, open(f"{a.out}/panel_info.json", "w"), indent=1)
    print(json.dumps({"launches": len(info), "rows": n_rows, "eligible_people": int(len(ok))}))


def pack(a) -> None:
    launches: dict[str, list[str]] = {}
    for line in open(a.gen):
        r = json.loads(line)
        if r["meta"].get("day") == a.day and r.get("text"):
            launches.setdefault(r["meta"]["slug"], []).append(" ".join(r["text"].split()))
    json.dump({"day": a.day, "arm": a.arm, "launches": launches}, open(a.out, "w"), indent=1)
    print(a.arm, "launches", len(launches), "comments", sum(len(v) for v in launches.values()))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--bench", required=True); b.add_argument("--lineup", required=True)
    b.add_argument("--day", required=True); b.add_argument("--out", required=True)
    b.add_argument("--panel", type=int, default=30); b.add_argument("--min-comments", type=int, default=3)
    p = sub.add_parser("pack")
    p.add_argument("--gen", required=True); p.add_argument("--arm", required=True)
    p.add_argument("--day", required=True); p.add_argument("--out", required=True)
    a = ap.parse_args()
    (build if a.cmd == "build" else pack)(a)


if __name__ == "__main__":
    main()
