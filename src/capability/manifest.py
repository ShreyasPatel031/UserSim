"""Bakeoff manifest helpers — slim checkpoints, trace merge, log recovery.

Full action traces live in trace_dir/run.json. The stage manifest only keeps
metadata so checkpoint writes stay fast and never block the worker pool.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from capability import OUT_DIR
from capability.browser_use_harness import stage1_config_snapshot
from capability.metrics import sort_runs, summarize

DONE_RE = re.compile(
    r"^DONE  mistral \| (\S+) \| idx=(\d+) \| (\S+) success=(\S+) actions=(\d+) cost=\$([0-9.]+)"
)


def slim_run(run: dict) -> dict:
    """Drop bulky action payloads from manifest rows (full trace stays on disk)."""
    out = {k: v for k, v in run.items() if k != "actions"}
    out["actions"] = []
    return out


def upsert_run(runs: list[dict], row: dict) -> None:
    """Replace an existing eval_index or append."""
    idx = row.get("eval_index")
    for i, r in enumerate(runs):
        if r.get("eval_index") == idx:
            runs[i] = row
            return
    runs.append(row)


def merge_runs_by_eval_index(runs: list[dict]) -> list[dict]:
    """Collapse duplicates, keeping the row with the latest created_at."""
    by_idx: dict[int | str, dict] = {}
    for r in runs:
        idx = r.get("eval_index")
        if idx is None:
            continue
        cur = by_idx.get(idx)
        if cur is None or (r.get("created_at") or "") >= (cur.get("created_at") or ""):
            by_idx[idx] = r
    return sort_runs(list(by_idx.values()))


def load_runs_from_traces(model: str, traces_dir: Path = OUT_DIR / "traces") -> list[dict]:
    runs: list[dict] = []
    if not traces_dir.is_dir():
        return runs
    for p in traces_dir.glob("mistral_*/run.json"):
        try:
            r = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if r.get("model") != model:
            continue
        idx = r.get("eval_index")
        if idx is None:
            continue
        runs.append(r)
    return merge_runs_by_eval_index(runs)


def stub_from_log_line(
    website: str,
    eval_index: int,
    status: str,
    success: bool,
    num_actions: int,
    cost: float,
    model: str,
    task_lookup: dict[int, dict],
) -> dict | None:
    task = task_lookup.get(eval_index)
    if not task:
        return None
    failure_category = None
    if not success:
        if status in {"BLOCKED", "JUDGE_ERROR"}:
            failure_category = status
        elif num_actions == 0:
            failure_category = "HARNESS"
        else:
            failure_category = "MODEL_REASONING"
    return {
        "run_id": f"log_{eval_index}",
        "task_id": task["task_id"],
        "eval_index": eval_index,
        "task": task["task"],
        "website": website,
        "model": model,
        "harness": "browser_use_oss",
        "provider": "mistral",
        "start_url": task["start_url"],
        "actions": [],
        "num_actions": num_actions,
        "stop_reason": "recovered_from_log",
        "success": success,
        "status": status,
        "failure_category": failure_category,
        "estimated_cost_usd": cost,
        "input_tokens": 0,
        "output_tokens": 0,
        "final_url": task["start_url"],
    }


def load_runs_from_log(
    log_path: Path,
    model: str,
    task_lookup: dict[int, dict],
) -> list[dict]:
    if not log_path.is_file():
        return []
    last: dict[int, tuple] = {}
    for line in log_path.read_text().splitlines():
        m = DONE_RE.match(line.strip())
        if not m:
            continue
        website, idx_s, status, success_s, actions_s, cost_s = m.groups()
        idx = int(idx_s)
        last[idx] = (
            website,
            status,
            success_s == "True",
            int(actions_s),
            float(cost_s),
        )
    runs: list[dict] = []
    for idx, (website, status, success, num_actions, cost) in last.items():
        stub = stub_from_log_line(website, idx, status, success, num_actions, cost, model, task_lookup)
        if stub:
            runs.append(stub)
    return runs


def write_manifest(
    path: Path,
    runs: list[dict],
    *,
    stage: str,
    model: str,
    max_actions: int,
    slim: bool = True,
) -> None:
    merged = merge_runs_by_eval_index(runs)
    rows = [slim_run(r) for r in merged] if slim else merged
    payload = {
        "stage": stage,
        "harness": "browser_use_oss",
        "provider": "mistral",
        "model": model,
        "max_actions_budget": max_actions,
        "harness_config": stage1_config_snapshot(),
        **summarize(merged),
        "runs": rows,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    tmp.replace(path)


def rebuild_manifest(
    path: Path,
    *,
    stage: str,
    model: str,
    max_actions: int,
    tasks: list[dict],
    log_path: Path | None = None,
) -> list[dict]:
    """Merge manifest file, trace run.json files, and optional log DONE lines."""
    task_lookup = {t["eval_index"]: t for t in tasks}
    merged: list[dict] = []

    if path.is_file():
        try:
            prev = json.loads(path.read_text())
            merged.extend(prev.get("runs") or [])
        except (json.JSONDecodeError, OSError):
            pass

    merged.extend(load_runs_from_traces(model))
    if log_path:
        merged.extend(load_runs_from_log(log_path, model, task_lookup))

    return merge_runs_by_eval_index(merged)
