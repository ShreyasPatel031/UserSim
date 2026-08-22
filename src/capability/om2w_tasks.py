"""Load Online-Mind2Web tasks for capability eval."""

from __future__ import annotations

import json
from pathlib import Path

from config import ROOT

from capability.mini2_tasks import MINI2_TASKS

OM2W_JSON = (
    ROOT
    / "vendor"
    / "fara"
    / "webeval"
    / "data"
    / "om2w"
    / "Online_Mind2Web_06042025.json"
)


def load_om2w_tasks(
    *,
    limit: int | None = None,
    mini2_only: bool = False,
    task_ids: list[str] | None = None,
) -> list[dict]:
    """Return normalized OM2W task dicts."""
    if mini2_only:
        rows = MINI2_TASKS
    else:
        raw = json.loads(OM2W_JSON.read_text())
        rows = []
        for ex in raw:
            rows.append(
                {
                    "task_id": ex["task_id"],
                    "website": ex["website"].rstrip("/").split("//")[-1].split("/")[0],
                    "start_url": ex["website"],
                    "task": ex["confirmed_task"],
                    "level": ex.get("level"),
                    "reference_length": ex.get("reference_length"),
                }
            )
        if task_ids:
            wanted = set(task_ids)
            rows = [r for r in rows if r["task_id"] in wanted]
        if limit is not None:
            rows = rows[:limit]

    out = []
    for i, t in enumerate(rows):
        out.append(
            {
                "task_id": t["task_id"],
                "eval_index": f"om2w_{i}",
                "website": t.get("website") or t["start_url"],
                "start_url": t["start_url"],
                "task": t["task"],
                "level": t.get("level"),
                "reference_length": t.get("reference_length"),
            }
        )
    return out
