"""Score comment generations from any source on the Task C rows, next to the references.

    python -m simharness.finetune.score_taskc --bench BENCH --out scores.json \\
        --gen tuned=gen_tuned.jsonl base=gen_base.jsonl flash=gen_{split}_history.parquet \\
        --pairs tuned-base tuned-flash [--tau 0.7497]

A generation file is JSONL with {"meta": {"split", "person_idx", "item_idx"}, "text"} (what finetune/lora.py writes)
or a parquet with person_idx, item_idx, sim_text; "{split}" in a path is replaced by the split name.
Passing --tau reuses a threshold fitted earlier instead of fitting it again.
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from simharness import task_c as tc
from simharness.bench import Benchmark

REFS = ("floor_other_item", "own_past_comment", "same_item_other")
METRICS = ("own_vs_other", "match")


def load_gen(path: str, split: str) -> dict:
    path = path.replace("{split}", split)
    if path.endswith(".parquet"):
        g = pd.read_parquet(path)
        return {(int(r.person_idx), int(r.item_idx)): r.sim_text for r in g.itertuples()}
    out = {}
    for line in open(path):
        r = json.loads(line)
        if r["meta"].get("split", split) == split:
            out[(int(r["meta"]["person_idx"]), int(r["meta"]["item_idx"]))] = r["text"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--gen", nargs="+", required=True, help="name=path ...")
    ap.add_argument("--pairs", nargs="*", default=[], help="a-b ... (a minus b, paired on the same rows)")
    ap.add_argument("--tau", type=float)
    ap.add_argument("--val-rows", type=int, default=400)
    a = ap.parse_args()
    T = tc.TaskC(Benchmark(a.bench))
    if a.tau:
        T.tau = a.tau
    gens = dict(g.split("=", 1) for g in a.gen)
    res = {"tau": T.tau, "splits": {}}
    for split, cap in (("val", a.val_rows), ("test", None)):
        rows = T.rows(split, max_rows=cap)
        sc = {ref: T.score_reference(rows, ref) for ref in REFS}
        for name, path in gens.items():
            g = load_gen(path, split)
            sc[name] = T.score(rows, [g.get((int(r.person_idx), int(r.item_idx))) for r in rows.itertuples()])
        R = {"rows": len(rows), "models": {}, "paired": {}}
        for k, v in sc.items():
            R["models"][k] = {**tc.summarize(v, n_boot=1000), "empty": int((~v["has"]).sum())}
        for pair in a.pairs:
            x, y = pair.split("-", 1)
            for m in METRICS:
                R["paired"][f"{x}-minus-{y}:{m}"] = tc.paired_diff(sc[x], sc[y], m, n_boot=1000)
        res["splits"][split] = R
        pct = lambda d: f"{100 * d['value']:.1f} [{100 * d['ci95'][0]:.1f}, {100 * d['ci95'][1]:.1f}]"  # noqa: E731
        print(split, len(rows), flush=True)
        for k, v in R["models"].items():
            print(f"  {k:22s} person {pct(v['own_vs_other'])} | content {pct(v['match'])} | len "
                  f"{v['len_ratio_median']['value']:.2f} | empty {v['empty']}", flush=True)
        for k, v in R["paired"].items():
            print(f"  PAIRED {k}: {100 * v['diff']:+.1f} [{100 * v['ci95'][0]:+.1f}, {100 * v['ci95'][1]:+.1f}] "
                  f"n={v['rows']}", flush=True)
    json.dump(res, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
