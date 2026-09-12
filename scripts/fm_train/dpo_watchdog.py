#!/usr/bin/env python3
"""On-VM watchdog for the Socrates DPO run (systemd timer, one poll).

Same contract as sft_watchdog.py but watches socrates_dpo/ and the DPO service.
Revives the unit after Spot reboot / crash when stage is incomplete.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
RESULTS = ROOT / "results" / "socrates_dpo"
LOG = ROOT / "results" / "socrates_dpo.log"
SERVICE = os.environ.get("DPO_SERVICE", "usersim-dpo-socrates.service")
STALL_MIN = float(os.environ.get("STALL_MIN", "45"))
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
    # Must match boot_socrates_dpo.py stamp names exactly.
    order = [
        "install_train_deps",
        "pairs_smoke",
        "format_smoke",
        "train_smoke",
        "pairs_full",
        "train_full",
        "eval_full",
        "decision",
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
    step = progress.get("step")
    marker = f"{stage}:{step}"

    last_marker = prev.get("marker")
    last_change = prev.get("last_change_ts", now)
    if marker != last_marker:
        last_change = now
    stalled_min = (now - last_change) / 60.0

    if progress.get("diverged"):
        alerts.append(f"diverged loss={progress.get('loss')}")
    if "CUDA out of memory" in tail or "OutOfMemoryError" in tail:
        alerts.append("cuda_oom")
    if "DPO FORMAT SMOKE FAIL" in tail or "FORMAT SMOKE FAIL" in tail:
        alerts.append("format_smoke_failed")
    try:
        if int(restarts or "0") >= 5:
            alerts.append(f"service_restarts={restarts}")
    except ValueError:
        pass

    revived = False
    if active != "active" and stage not in ("complete",):
        if active in ("inactive", "failed"):
            start_out = run(["systemctl", "start", SERVICE], timeout=30)
            revived = True
            print(f"revived {SERVICE} from {active}: {start_out}", flush=True)
            active = run(["systemctl", "is-active", SERVICE])
            if active == "failed":
                alerts.append("service_failed")
    if stalled_min > STALL_MIN and stage not in ("complete",) and active == "active":
        boot_age_min = (now - float(prev.get("first_seen_ts", now))) / 60.0
        if boot_age_min > GRACE_MIN:
            alerts.append(f"stalled_{stalled_min:.0f}min stage={stage}")
            run(["systemctl", "restart", SERVICE], timeout=30)
            revived = True

    snap = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "service": SERVICE,
        "active": active,
        "restarts": restarts,
        "stage": stage,
        "marker": marker,
        "last_change_ts": last_change,
        "first_seen_ts": prev.get("first_seen_ts", now),
        "stalled_min": round(stalled_min, 1),
        "progress": progress,
        "gpu": gpu_snapshot(),
        "alerts": alerts,
        "revived": revived,
        "role": "dpo",
    }
    STATE.write_text(json.dumps(snap, indent=2) + "\n")
    if alerts:
        ALERT.write_text(json.dumps(snap, indent=2) + "\n")
        print("ALERT", alerts, flush=True)
    else:
        if ALERT.exists():
            ALERT.unlink()
        print("ok", stage, marker, flush=True)


if __name__ == "__main__":
    main()
