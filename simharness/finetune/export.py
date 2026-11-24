"""Export chat-format rows for fine-tuning and for scoring a tuned model (Task C: history + item -> real comment).

    python -m simharness.finetune.export --bench BENCH --out OUT [--train-rows 4000] [--per-person 15]

Writes OUT/train.jsonl ({"messages": [user, assistant]}) and OUT/eval.jsonl (the validation and test rows the Task C
scorer uses, each {"messages": [user], "meta": {split, person_idx, item_idx, day}}).

Leak rules are the benchmark's: a row's history holds only items of earlier days and comments written before the row's
day starts. Training rows come from the training split only; a person's earlier comments may appear both as training
targets and in a later row's history, which is what "built from the person's history" means.

OUT holds real comment text: keep it private (never in this repository).
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from simharness.bench import Benchmark
from simharness.task_c import TaskC, _item_fields

FT_PROMPT = """You write the comment one real Product Hunt member leaves on a launch.

THIS MEMBER'S HISTORY (everything known before today):
{history}

TODAY'S LAUNCH:
Name: {title}
Tagline: {summary}
Description: {description}
Topics: {tags}

This member did comment on this launch today. Write that comment as they would: their usual length, tone, focus and
kind of question or praise, as their past comments show. Reply with the comment only."""


def prompt_for(bench, row, max_items: int = 30, max_comments: int = 10) -> str:
    batch = bench.batch(row.day, np.array([row.person_idx]))
    return FT_PROMPT.format(history=batch.render(0, max_items, max_comments), **_item_fields(bench.item(row.item_idx)))


def train_rows(task: TaskC, n: int, per_person: int) -> pd.DataFrame:
    """The most recent training comments (day-of, not by a maker), at most `per_person` per person."""
    r = task._day_of[(task._day_of["split"] == "train") & ~task._day_of["is_maker"]]
    r = r.sort_values(["day", "ts"], ascending=False)
    r = r[r.groupby("person_idx").cumcount() < per_person]
    return r.head(n).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--train-rows", type=int, default=4000)
    ap.add_argument("--per-person", type=int, default=15)
    ap.add_argument("--val-rows", type=int, default=400)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    bench = Benchmark(a.bench)
    task = TaskC(bench)
    tr = train_rows(task, a.train_rows, a.per_person)
    with open(f"{a.out}/train.jsonl", "w") as f:
        for row in tr.itertuples():
            f.write(json.dumps({"messages": [{"role": "user", "content": prompt_for(bench, row)},
                                             {"role": "assistant", "content": " ".join(str(row.text).split())}]}) + "\n")
    n_eval = 0
    with open(f"{a.out}/eval.jsonl", "w") as f:
        for split, cap in (("val", a.val_rows), ("test", None)):
            for row in task.rows(split, max_rows=cap).itertuples():
                f.write(json.dumps({"messages": [{"role": "user", "content": prompt_for(bench, row)}],
                                    "meta": {"split": split, "person_idx": int(row.person_idx),
                                             "item_idx": int(row.item_idx), "day": row.day}}) + "\n")
                n_eval += 1
    info = {"train_rows": len(tr), "train_people": int(tr.person_idx.nunique()), "train_first_day": tr.day.min(),
            "train_last_day": tr.day.max(), "eval_rows": n_eval, "per_person": a.per_person}
    json.dump(info, open(f"{a.out}/export_info.json", "w"), indent=1)
    print(json.dumps(info))


if __name__ == "__main__":
    main()
