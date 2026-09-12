#!/usr/bin/env python3
"""Build BehaviorBench leakage registry: hashed eval prompts + source IDs.

Writes results/fm_baselines/leakage_registry.jsonl (one record per blocked item)
and a small summary JSON beside it.

Never train on any (system, user, assistant) triple whose prompt_hash or
exact_hash appears here. For Big Five, also block subject_idx values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BB = ROOT / "data" / "fm_baselines" / "BehaviorBench"
DEFAULT_OUT = ROOT / "results" / "fm_baselines" / "leakage_registry.jsonl"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_key(system: str, user: str) -> str:
    return sha256(f"{system}\n\n{user}")


def exact_key(system: str, user: str, assistant: str) -> str:
    return sha256(f"{system}\n\n{user}\n\n{assistant}")


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def parse_demo_fingerprint(system: str) -> str | None:
    """Normalize BehaviorBench persona system strings to a match key."""
    # "You are a 16-year-old male from PT. You are Right-handed. ..."
    m = re.search(
        r"You are a (\d+)-year-old (male|female|other) from ([A-Z]{2})",
        system,
        re.I,
    )
    if not m:
        return None
    age, sex, country = m.group(1), m.group(2).lower(), m.group(3).upper()
    hand = "unknown"
    hm = re.search(r"(Right|Left|Both|Neither)-handed", system, re.I)
    if hm:
        hand = hm.group(1).lower()
    race = "unknown"
    rm = re.search(r"Your race is ([^.]+)\.", system)
    if rm:
        race = rm.group(1).strip().lower()
    eng = "unknown"
    if "native language is English" in system:
        eng = "yes"
    elif "native language is not English" in system:
        eng = "no"
    return f"age={age}|sex={sex}|country={country}|hand={hand}|race={race}|eng={eng}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bb-data", type=Path, default=DEFAULT_BB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    bb: Path = args.bb_data
    indices_path = bb / "behaviorbench_indices.json"
    indices = json.loads(indices_path.read_text()) if indices_path.exists() else {}

    records: list[dict] = []
    seen_exact: set[str] = set()
    subject_idxs: set[int] = set()
    demo_fps: set[str] = set()
    task_counts: Counter[str] = Counter()

    # Index entries: block upstream row IDs per task.
    for task, idxs in indices.items():
        for i in idxs:
            records.append(
                {
                    "kind": "source_index",
                    "task": task,
                    "source_index": int(i),
                    "hash": sha256(f"{task}:{int(i)}"),
                }
            )
            task_counts[f"index:{task}"] += 1

    for path in sorted(bb.rglob("*.jsonl")):
        rel = str(path.relative_to(bb))
        task = rel.replace("/test.jsonl", "").replace(".jsonl", "")
        for row_i, row in enumerate(load_jsonl(path)):
            system = row.get("system") or ""
            user = row.get("user") or ""
            assistant = row.get("assistant") or ""
            ph = prompt_key(system, user)
            eh = exact_key(system, user, assistant)
            meta = row.get("metadata") or {}
            rec = {
                "kind": "eval_example",
                "task": task,
                "path": rel,
                "row": row_i,
                "prompt_hash": ph,
                "exact_hash": eh,
                "assistant": assistant,
            }
            if "subject_idx" in meta:
                sid = int(meta["subject_idx"])
                rec["subject_idx"] = sid
                subject_idxs.add(sid)
            fp = parse_demo_fingerprint(system)
            if fp:
                rec["demo_fingerprint"] = fp
                demo_fps.add(fp)
            if eh not in seen_exact:
                seen_exact.add(eh)
                records.append(rec)
                task_counts[f"exact:{task}"] += 1

    # Explicit subject_idx blocklist entries (deduped).
    for sid in sorted(subject_idxs):
        records.append(
            {
                "kind": "subject_idx",
                "subject_idx": sid,
                "hash": sha256(f"subject_idx:{sid}"),
            }
        )

    for fp in sorted(demo_fps):
        records.append(
            {
                "kind": "demo_fingerprint",
                "demo_fingerprint": fp,
                "hash": sha256(f"demo:{fp}"),
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bb_data": str(bb),
        "out": str(args.out),
        "n_records": len(records),
        "n_exact_eval": len(seen_exact),
        "n_subject_idx": len(subject_idxs),
        "n_demo_fingerprint": len(demo_fps),
        "n_index_tasks": len(indices),
        "task_counts": dict(sorted(task_counts.items())),
    }
    summary_path = args.out.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
