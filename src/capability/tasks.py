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

# 8-task slice (full10 minus Under Armour + Eventbrite)
FULL8_INDICES = TASK_INDICES[:8]

# Smoke: one search+filter (Newegg), one multi-filter (Under Armour)
SMOKE_INDICES = [8, 25]

# 5-task bakeoff covering search / filter / select / final-goal
BAKEOFF5_INDICES = [25, 8, 34, 26, 19]  # UA, Newegg, Eventbrite, RT, Uniqlo

# All Mind2Web tasks shipped in data/mind2web_tasks.json
ALL_INDICES = sorted(_BY_IDX.keys())

# First 80 Mind2Web tasks (eval_index 0–79)
FULL80_INDICES = ALL_INDICES[:80]

# Hard-20: genuine model failures from full100 Flash audit (see results/capability/hard20.json).
# Flash baseline is 0/20 by construction — selected from failures; no Flash rerun needed.
HARD20_INDICES = [
    4,
    6,
    25,
    30,
    68,
    88,
    55,
    85,  # long multi-filter / step-cap heavy
    3,
    9,
    76,
    53,
    12,  # final-action
    57,
    19,
    50,
    5,  # navigation/search
    35,
    42,
    94,  # recovery
]

# All 27 genuine model failures from failure_audit_45.json (excludes site/harness).
_GENUINE_CAUSES = {
    "STEP_CAP",
    "PREMATURE_DONE",
    "PLANNING",
    "PERCEPTION",
    "GROUNDING",
    "RECOVERY",
}
_AUDIT_PATH = ROOT / "results" / "capability" / "failure_audit_45.json"
if _AUDIT_PATH.exists():
    _audit = json.loads(_AUDIT_PATH.read_text())
    GENUINE_FAIL_INDICES = sorted(
        f["eval_index"]
        for f in _audit["failures"]
        if f.get("primary_cause") in _GENUINE_CAUSES
    )
else:
    GENUINE_FAIL_INDICES = list(HARD20_INDICES)


def load_tasks(indices: list[int] | None = None) -> list[dict]:
    idxs = indices or TASK_INDICES
    out = []
    for i in idxs:
        t = _BY_IDX[i]
        website = t["website"]
        if website not in SITE_URLS:
            raise KeyError(f"No start URL for website={website!r} (eval_index={i})")
        out.append(
            {
                "task_id": t["annotation_id"],
                "eval_index": i,
                "website": website,
                "domain": t.get("domain"),
                "task": t["confirmed_task"],
                "start_url": SITE_URLS[website],
                "human_n_steps": t["n_steps"],
                "human_actions": list(t.get("action_reprs") or []),
            }
        )
    return out
