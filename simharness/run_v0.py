"""Command line for Benchmark v0 (Product Hunt adapter). All paths point at private data; nothing is bundled.

  python -m simharness.run_v0 build --store STORE_DIR --items ITEMS.parquet [--items MORE.parquet]
        [--comment-texts TEXTS.parquet | --records 'records/part-*.parquet'] --out BENCH_DIR
  python -m simharness.run_v0 baselines --bench BENCH_DIR --split test --out RESULTS_DIR

STORE_DIR holds persons.parquet, tabs.parquet and events.parquet from the population store.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle

import pandas as pd


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--store", required=True)
    b.add_argument("--items", action="append", required=True)
    b.add_argument("--comment-texts")
    b.add_argument("--records")
    b.add_argument("--out", required=True)
    e = sub.add_parser("baselines")
    e.add_argument("--bench", required=True)
    e.add_argument("--split", default="test")
    e.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "build":
        from simharness.bench import build
        from simharness.domains.producthunt import build_tables
        ct = pd.read_parquet(a.comment_texts) if a.comment_texts else None
        tables = build_tables(a.store, a.items, records_glob=a.records, comment_texts=ct)
        print(json.dumps(build(tables, a.out)["sizes"], indent=1))
    else:
        from simharness.bench import Benchmark
        from simharness.models.baselines import backer_logistic, most_active
        from simharness.score import evaluate_full, paired_diff, summarize, write_leaderboard
        bench = Benchmark(a.bench)
        os.makedirs(a.out, exist_ok=True)
        res, entries = {}, []
        for m in (most_active(), backer_logistic()):
            res[m.name] = evaluate_full(m, bench, bench.days(a.split))
            entries.append({"model": m.name, "eval": f"{a.split}, full pool", "summary": summarize(res[m.name])})
        with open(f"{a.out}/per_item_{a.split}.pkl", "wb") as f:
            pickle.dump(res, f)
        write_leaderboard(entries, f"{a.out}/leaderboard_{a.split}.json", f"{a.out}/leaderboard_{a.split}.md")
        n = list(res)
        print(json.dumps(paired_diff(res[n[1]], res[n[0]])))


if __name__ == "__main__":
    main()
