#!/usr/bin/env python3
"""On-VM watchdog for the Socrates SFT run.

One poll per invocation (driven by a systemd timer). It answers the only two
questions that matter between check-ins: is the job still making progress, and
is the run healthy enough to be worth continuing?

Writes `results/socrates_sft/WATCHDOG.json` — a compact snapshot the cloud
agent pulls every couple of hours — and `ALERT.json` when something needs a
human or agent decision (divergence, repeated restarts, OOM, stuck stage).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
RESULTS = ROOT / "results" / "socrates_sft"
LOG = ROOT / "results" / "socrates_sft.log"
SERVICE = os.environ.get("SFT_SERVICE", "usersim-sft-socrates.service")
STALL_MIN = float(os.environ.get("STALL_MIN", "30"))
GRACE_MIN = float(os.environ.get("GRACE_MIN", "40"))
STATE = RESULTS / "WATCHDOG.json"
ALERT = RESULTS / "ALERT.json"


def run(cmd: list[str], timeout: int = 60) -> str:
    try:
        r = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:  # noqa: BLE001
        return f"ERR {exc}"


def log_tail(n_bytes: int = 20000) -> str:
    if not LOG.exists():
        return ""
    with LOG.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - n_bytes))
        return f.read().decode("utf-8", "replace")


def gpu_snapshot() -> dict:
    out = run(
        [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ]
    )
    parts = [p.strip() for p in out.split(",")]
    if len(parts) == 3 and parts[0].isdigit():
        return {
            "util_pct": int(parts[0]),
            "mem_used_mb": int(parts[1]),
            "mem_total_mb": int(parts[2]),
        }
    return {"raw": out}


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return None


def current_stage() -> str:
    stamps = RESULTS / "stamps"
    order = [
        "install",
        "corpus_smoke",
        "format_smoke",
        "train_smoke",
        "eval_smoke",
        "corpus_full",
        "train_full",
        "eval_full",
    ]
    done = {p.name for p in stamps.glob("*")} if stamps.exists() else set()
    for name in order:
        if name not in done:
            return name
    return "complete"


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    now = time.time()
    prev = read_json(STATE) or {}
    progress = read_json(RESULTS / "PROGRESS.json") or {}
    tail = log_tail()
    alerts: list[str] = []

    active = run(["systemctl", "is-active", SERVICE])
    restarts = run(["systemctl", "show", "-p", "NRestarts", "--value", SERVICE])
    stage = current_stage()

    # Progress marker: train step, else eval prediction count.
    step = progress.get("step")
    eval_preds = 0
    for sub in ("eval_smoke", "eval_full"):
        p = RESULTS / sub / "predictions.jsonl"
        if p.exists():
            eval_preds += sum(1 for _ in p.open())
    marker = f"{stage}:{step}:{eval_preds}"

    last_marker = prev.get("marker")
    last_change = prev.get("last_change_ts", now)
    if marker != last_marker:
        last_change = now
    stalled_min = (now - last_change) / 60.0

    started_at = prev.get("started_at", now)
    uptime_min = (now - started_at) / 60.0

    if progress.get("diverged"):
        alerts.append(f"loss diverged at step {progress.get('step')}")
    loss = progress.get("loss")
    if isinstance(loss, (int, float)) and loss > 20:
        alerts.append(f"loss implausibly high ({loss})")
    if re.search(r"CUDA out of memory|OutOfMemoryError", tail):
        alerts.append("CUDA OOM in log")
    if re.search(r"FORMAT SMOKE FAIL", tail):
        alerts.append("format smoke failed")
    if re.search(r"Traceback \(most recent call last\)", tail) and active != "active":
        alerts.append("service not active after traceback")
    try:
        if int(restarts) >= 3:
            alerts.append(f"service restarted {restarts} times")
    except ValueError:
        pass
    if stage != "complete" and active != "active":
        alerts.append(f"service {active} while stage {stage} incomplete")
    if stalled_min > STALL_MIN and uptime_min > GRACE_MIN and stage != "complete":
        alerts.append(f"no progress for {stalled_min:.0f} min at stage {stage}")

    if alerts and active != "active" and stage != "complete":
        run(["sudo", "systemctl", "restart", SERVICE], timeout=120)
        alerts.append("watchdog restarted the service")

    snapshot = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "stage": stage,
        "service_active": active,
        "service_restarts": restarts,
        "train_progress": {
            k: progress.get(k)
            for k in ("step", "max_steps", "epoch", "loss", "grad_norm", "elapsed_s")
        },
        "eval_predictions": eval_preds,
        "gpu": gpu_snapshot(),
        "marker": marker,
        "last_change_ts": last_change,
        "stalled_min": round(stalled_min, 1),
        "started_at": started_at,
        "alerts": alerts,
        "log_tail": tail[-1500:],
    }
    STATE.write_text(json.dumps(snapshot, indent=2) + "\n")
    if alerts:
        ALERT.write_text(json.dumps(snapshot, indent=2) + "\n")
        print("ALERTS: " + "; ".join(alerts), flush=True)
    else:
        if ALERT.exists():
            ALERT.unlink()
        print(f"ok stage={stage} marker={marker} stalled={stalled_min:.0f}min", flush=True)


if __name__ == "__main__":
    main()
