"""Fixed 10-task capability benchmark (same as v0.6 live set)."""

from __future__ import annotations

import json
from pathlib import Path

from config import ROOT

SITE_URLS = json.loads((ROOT / "data" / "site_urls.json").read_text())
_TASKS = json.loads((ROOT / "data" / "mind2web_tasks.json").read_text())["tasks"]
_BY_IDX = {t["eval_index"]: t for t in _TASKS}

# Same 10 as v0.6 free-run PREFERRED
TASK_INDICES = [32, 26, 33, 8, 19, 22, 7, 12, 25, 34]

# Smoke: one search+filter (Newegg), one multi-filter (Under Armour)
SMOKE_INDICES = [8, 25]

# 5-task bakeoff covering search / filter / select / final-goal
BAKEOFF5_INDICES = [25, 8, 34, 26, 19]  # UA, Newegg, Eventbrite, RT, Uniqlo


def load_tasks(indices: list[int] | None = None) -> list[dict]:
    idxs = indices or TASK_INDICES
    out = []
    for i in idxs:
        t = _BY_IDX[i]
        out.append(
            {
                "task_id": t["annotation_id"],
                "eval_index": i,
                "website": t["website"],
                "domain": t.get("domain"),
                "task": t["confirmed_task"],
                "start_url": SITE_URLS[t["website"]],
                "human_n_steps": t["n_steps"],
                "human_actions": list(t.get("action_reprs") or []),
            }
        )
    return out
