#!/usr/bin/env python3
"""Export successful Browser Use traces → Mistral fine-tune JSONL.

Hackathon path: distill Gemini teacher trajectories into a Mistral student.
Input: results/capability/traces/bu_*/run.json (+ conversation/ if present)
Output: data/hackathon/mistral_sft.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_messages(conv_dir: Path) -> list[dict] | None:
    if not conv_dir.is_dir():
        return None
    files = sorted(conv_dir.glob("conversation_*.txt"))
    if not files:
        return None
  # Browser Use saves human-readable logs, not strict JSON — pack as single user turn.
    text = files[-1].read_text(errors="replace")[:120_000]
    return [
        {
            "role": "system",
            "content": "You are a web browsing agent. Complete tasks using browser actions.",
        },
        {"role": "user", "content": text},
    ]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--traces", type=Path, default=Path("results/capability/traces"))
    p.add_argument("--out", type=Path, default=Path("data/hackathon/mistral_sft.jsonl"))
    p.add_argument("--success-only", action="store_true", default=True)
    args = p.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with args.out.open("w") as fout:
        for run_path in sorted(args.traces.glob("bu_*/run.json")):
            row = json.loads(run_path.read_text())
            if args.success_only and not row.get("success"):
                continue
            messages = _load_messages(run_path.parent / "conversation")
            if not messages:
                task = row.get("task", "")
                actions = row.get("actions") or []
                summary = "\n".join(
                    f"{a.get('i')}: {a.get('action')} @ {a.get('url')}" for a in actions
                )
                messages = [
                    {
                        "role": "system",
                        "content": "You are a web browsing agent.",
                    },
                    {
                        "role": "user",
                        "content": f"Task: {task}\n\nCompleted trajectory:\n{summary}",
                    },
                ]
            record = {"messages": messages}
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            n += 1
    print(f"Wrote {n} rows → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
