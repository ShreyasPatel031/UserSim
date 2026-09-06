#!/usr/bin/env python3
"""Always-on Spot watchdog for Gate-0 FM VMs.

Why
---
Spot/preemptible VMs stop on preemption and stay TERMINATED until something
starts them again. This process is meant to run on a tiny *on-demand*
e2-micro so it cannot itself be preempted.

Behavior (matches "event → poll while down → clear when up")
----------------------------------------------------------
1. List instances labeled usersim-spot-watch=true in this project.
2. If status is TERMINATED / STOPPED: create a watch session file and
   attempt `gcloud compute instances start`.
3. While a session exists, keep retrying every poll (capacity can be
   temporarily unavailable after preemption — we saw 503s).
4. When the instance is RUNNING again: delete the session file
   ("get deleted when back up").
5. Never deletes/stops this watchdog VM — without Eventarc it is the
   durable trigger for the *next* preemption.

Env
---
  GCP_PROJECT          default: gcloud config project
  WATCH_LABEL_KEY      default: usersim-spot-watch
  WATCH_LABEL_VALUE    default: true
  STATE_DIR            default: /var/lib/usersim-spot-watch
  POLL_SEC             default: 60 (used by systemd timer; script is one-shot)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

LABEL_KEY = os.environ.get("WATCH_LABEL_KEY", "usersim-spot-watch")
LABEL_VALUE = os.environ.get("WATCH_LABEL_VALUE", "true")
STATE_DIR = Path(os.environ.get("STATE_DIR", "/var/lib/usersim-spot-watch"))
LOG = Path(os.environ.get("WATCH_LOG", "/var/log/usersim-spot-watch.log"))


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " " + msg
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def project() -> str:
    p = os.environ.get("GCP_PROJECT") or os.environ.get("CLOUDSDK_CORE_PROJECT")
    if p:
        return p
    r = run(["gcloud", "config", "get-value", "project"], timeout=30)
    return (r.stdout or "").strip()


def list_watched() -> list[dict]:
    """Return [{name, zone, status}, ...] for labeled instances."""
    filt = f"labels.{LABEL_KEY}={LABEL_VALUE}"
    r = run(
        [
            "gcloud",
            "compute",
            "instances",
            "list",
            f"--project={project()}",
            f"--filter={filt}",
            "--format=json(name,zone,status)",
        ],
        timeout=120,
    )
    if r.returncode != 0:
        log(f"list FAILED: {(r.stderr or r.stdout)[-400:]}")
        return []
    try:
        rows = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        log("list: bad json")
        return []
    out = []
    for row in rows:
        zone = row.get("zone", "")
        if "/" in zone:
            zone = zone.rsplit("/", 1)[-1]
        out.append(
            {
                "name": row["name"],
                "zone": zone,
                "status": row.get("status", "UNKNOWN"),
            }
        )
    return out


def session_path(name: str) -> Path:
    return STATE_DIR / f"{name}.watching.json"


def open_session(inst: dict, reason: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = session_path(inst["name"])
    payload = {
        "name": inst["name"],
        "zone": inst["zone"],
        "reason": reason,
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "attempts": 0,
    }
    if path.exists():
        try:
            payload = json.loads(path.read_text())
        except Exception:
            pass
    payload["attempts"] = int(payload.get("attempts", 0)) + 1
    payload["last_attempt_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload["last_status"] = inst["status"]
    path.write_text(json.dumps(payload, indent=2))
    log(f"SESSION open {inst['name']} attempt={payload['attempts']} status={inst['status']}")


def close_session(name: str) -> None:
    path = session_path(name)
    if path.exists():
        path.unlink()
        log(f"SESSION deleted {name} (instance back UP)")


def start_instance(inst: dict) -> bool:
    r = run(
        [
            "gcloud",
            "compute",
            "instances",
            "start",
            inst["name"],
            f"--zone={inst['zone']}",
            f"--project={project()}",
        ],
        timeout=300,
    )
    out = ((r.stdout or "") + (r.stderr or ""))[-600:]
    if r.returncode == 0:
        log(f"START ok {inst['name']} ({inst['zone']})")
        return True
    log(f"START fail {inst['name']}: {out}")
    return False


def tick() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    watched = list_watched()
    if not watched:
        log(f"no instances with {LABEL_KEY}={LABEL_VALUE}")
        return 0

    down_like = {"TERMINATED", "STOPPED"}
    n_start = 0
    for inst in watched:
        name, status = inst["name"], inst["status"]
        if status in down_like:
            open_session(inst, reason=f"status={status}")
            if start_instance(inst):
                n_start += 1
            else:
                log(f"will retry {name} on next poll (Spot capacity / 503)")
        elif status == "RUNNING":
            if session_path(name).exists():
                close_session(name)
            else:
                log(f"ok {name} RUNNING")
        elif status in {"STAGING", "PROVISIONING", "REPAIRING"}:
            open_session(inst, reason=f"status={status}")
            log(f"wait {name} {status}")
        else:
            log(f"note {name} status={status}")

    # orphan sessions (instance no longer labeled / deleted)
    live = {i["name"] for i in watched}
    for path in STATE_DIR.glob("*.watching.json"):
        name = path.name[: -len(".watching.json")]
        if name not in live:
            path.unlink()
            log(f"SESSION deleted {name} (no longer watched)")

    return n_start


def main() -> int:
    log(f"watchdog tick project={project()} label={LABEL_KEY}={LABEL_VALUE}")
    try:
        n = tick()
    except Exception as e:
        log(f"FATAL {type(e).__name__}: {e}")
        return 1
    log(f"watchdog done starts_attempted={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
