"""Online-Mind2Web (OM2W) task loader — 300 maintained live tasks."""

from __future__ import annotations

import json
from pathlib import Path

from config import ROOT

_TASKS_PATH = ROOT / "data" / "om2w" / "om2w_tasks.json"
_TASKS = json.loads(_TASKS_PATH.read_text())["tasks"]
_BY_IDX = {t["eval_index"]: t for t in _TASKS}

# Default slices (eval_index into OM2W 300).
TASK_INDICES = list(range(10))  # full10
FULL8_INDICES = list(range(8))
SMOKE_INDICES = [0, 1]
BAKEOFF5_INDICES = list(range(5))
ALL_INDICES = sorted(_BY_IDX.keys())  # 0..299
FULL80_INDICES = ALL_INDICES[:80]
FULL100_INDICES = ALL_INDICES[:100]
FULL300_INDICES = ALL_INDICES

# Legacy Hard-20 / genuine-fail indices pointed at the old 100-task dump.
# Recompute after an OM2W Flash-Lite failure audit; empty until then.
HARD20_INDICES: list[int] = []
GENUINE_FAIL_INDICES: list[int] = []


def load_tasks(indices: list[int] | None = None) -> list[dict]:
    idxs = indices or TASK_INDICES
    out = []
    for i in idxs:
        t = _BY_IDX[i]
        start_url = t.get("start_url")
        if not start_url:
            raise KeyError(f"No start_url for eval_index={i} task_id={t.get('task_id')}")
        out.append(
            {
                "task_id": t["task_id"],
                "eval_index": i,
                "website": t["website"],
                "website_host": t.get("website_host"),
                "domain": t.get("domain"),
                "task": t.get("task") or t.get("confirmed_task") or "",
                "start_url": start_url,
                "human_n_steps": int(t.get("n_steps") or t.get("reference_length") or 0),
                "human_actions": list(t.get("action_reprs") or []),
                "difficulty": t.get("difficulty"),
                "benchmark": "Online-Mind2Web",
            }
        )
    return out
