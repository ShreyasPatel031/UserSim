"""Hard gates for FM GPU evals. Import or run via preflight_gpu_eval.py."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIN_CONCURRENCY = 32
MIN_MAX_NUM_SEQS = 64
REQUIRED_ENGINE = "vllm"
SMOKE_NAME = "SMOKE_OK.json"

PRED_KEYS = {"prompt", "raw_output", "parsed_prediction", "expected"}
RESULT_TOP = {"timestamp", "metrics", "num_tasks", "tasks"}


def require_vllm_concurrency(concurrency: int, max_num_seqs: int) -> None:
    if concurrency < MIN_CONCURRENCY:
        raise SystemExit(
            f"PROTOCOL: concurrency={concurrency} < {MIN_CONCURRENCY}. "
            "vLLM max concurrency is mandatory."
        )
    if max_num_seqs < MIN_MAX_NUM_SEQS:
        raise SystemExit(
            f"PROTOCOL: max_num_seqs={max_num_seqs} < {MIN_MAX_NUM_SEQS}."
        )


def smoke_ok_path(results_dir: Path) -> Path:
    return results_dir / SMOKE_NAME


def require_smoke(results_dir: Path) -> dict[str, Any]:
    path = smoke_ok_path(results_dir)
    if not path.exists():
        raise SystemExit(
            f"PROTOCOL: missing {path}. Run MODE=smoke first and get SMOKE_PASSED."
        )
    data = json.loads(path.read_text())
    if data.get("engine") != REQUIRED_ENGINE:
        raise SystemExit(f"PROTOCOL: smoke engine={data.get('engine')} not {REQUIRED_ENGINE}")
    if not data.get("passed"):
        raise SystemExit("PROTOCOL: SMOKE_OK exists but passed=false")
    return data


def validate_harness_json(path: Path, expect_task: str) -> dict[str, Any]:
    data = json.loads(path.read_text())
    missing = RESULT_TOP - set(data)
    if missing:
        raise AssertionError(f"{path.name}: missing top keys {missing}")
    if not data.get("tasks"):
        raise AssertionError(f"{path.name}: empty tasks")
    task = data["tasks"][0]
    if task.get("task_name") != expect_task:
        raise AssertionError(f"expected {expect_task}, got {task.get('task_name')}")
    preds = task.get("predictions") or []
    if not preds:
        raise AssertionError(f"{path.name}: no predictions")
    sample = preds[0]
    miss = PRED_KEYS - set(sample)
    if miss:
        raise AssertionError(f"{path.name}: prediction missing {miss}")
    parsed_ok = sum(1 for p in preds if p.get("parsed_prediction") is not None)
    if parsed_ok < 1:
        raise AssertionError(f"{path.name}: zero parsed_prediction values")
    return {
        "task": expect_task,
        "n_preds": len(preds),
        "parsed_non_null": parsed_ok,
        "failed_parse_rate": (task.get("metadata") or {}).get("failed_parse_rate"),
        "file": str(path),
    }


def write_smoke_ok(results_dir: Path, reports: list[dict[str, Any]], extra: dict[str, Any]) -> Path:
    payload = {
        "passed": True,
        "engine": REQUIRED_ENGINE,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "reports": reports,
        **extra,
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    path = smoke_ok_path(results_dir)
    path.write_text(json.dumps(payload, indent=2))
    return path


def watchdog_armed() -> bool:
    """True if the launching env marked watchdog as armed (preflight wrote this)."""
    flag = os.environ.get("WATCHDOG_ARMED", "").strip()
    if flag in {"1", "true", "TRUE"}:
        return True
    marker = Path(os.environ.get("WATCHDOG_MARKER", "/opt/usersim_fm/WATCHDOG_ARMED"))
    return marker.exists()


def require_watchdog() -> None:
    if os.environ.get("SKIP_WATCHDOG", "").strip() in {"1", "true", "TRUE"}:
        raise SystemExit("PROTOCOL: SKIP_WATCHDOG is not allowed for full runs.")
    if not watchdog_armed():
        raise SystemExit(
            "PROTOCOL: watchdog not armed. Run preflight_gpu_eval.py "
            "(spot-watch label + systemd + watchdog VM) first."
        )
