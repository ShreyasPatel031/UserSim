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
2. Skip anything labeled usersim-do-not-start=true, anything whose name is
   in NEVER_START, or anything whose usersim-fleet label ends in -retired.
3. If status is TERMINATED / STOPPED: create a watch session file and
   attempt `gcloud compute instances start`.
4. While a session exists, keep retrying every poll (capacity can be
   temporarily unavailable after preemption — we saw 503s).
5. When the instance is RUNNING again: delete the session file
   ("get deleted when back up").
6. Never deletes/stops this watchdog VM — without Eventarc it is the
   durable trigger for the *next* preemption.

Env
---
  GCP_PROJECT          default: gcloud config project
  WATCH_LABEL_KEY      default: usersim-spot-watch
  WATCH_LABEL_VALUE    default: true
  DENY_LABEL_KEY       default: usersim-do-not-start
  NEVER_START          comma-separated names, default: fm-gate0-minitaur
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
DENY_LABEL_KEY = os.environ.get("DENY_LABEL_KEY", "usersim-do-not-start")
NEVER_START = {
    n.strip()
    for n in os.environ.get("NEVER_START", "fm-gate0-minitaur").split(",")
    if n.strip()
}
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
    """Return [{name, zone, status, labels}, ...] for labeled instances."""
    filt = f"labels.{LABEL_KEY}={LABEL_VALUE}"
    r = run(
        [
            "gcloud",
            "compute",
            "instances",
            "list",
            f"--project={project()}",
            f"--filter={filt}",
            "--format=json(name,zone,status,labels)",
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
                "labels": row.get("labels") or {},
            }
        )
    return out


def is_denied(inst: dict) -> str | None:
    """Return a reason string if this instance must never be started."""
    name = inst["name"]
    labels = inst.get("labels") or {}
    if name in NEVER_START:
        return f"name in NEVER_START"
    if str(labels.get(DENY_LABEL_KEY, "")).lower() in {"true", "1", "yes"}:
        return f"label {DENY_LABEL_KEY}=true"
    fleet = str(labels.get("usersim-fleet", ""))
    if fleet.endswith("-retired"):
        return f"fleet={fleet}"
    return None


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


def close_session(name: str, why: str = "instance back UP") -> None:
    path = session_path(name)
    if path.exists():
        path.unlink()
        log(f"SESSION deleted {name} ({why})")


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


def stop_instance(inst: dict) -> bool:
    r = run(
        [
            "gcloud",
            "compute",
            "instances",
            "stop",
            inst["name"],
            f"--zone={inst['zone']}",
            f"--project={project()}",
        ],
        timeout=300,
    )
    out = ((r.stdout or "") + (r.stderr or ""))[-600:]
    if r.returncode == 0:
        log(f"STOP ok {inst['name']} ({inst['zone']}) — denied instance was running")
        return True
    log(f"STOP fail {inst['name']}: {out}")
    return False


def list_denied_running() -> list[dict]:
    """Find NEVER_START / do-not-start VMs that some other actor brought up.

    The watch-label filter alone is not enough: an external starter (or a
    briefly re-applied watch label) has revived fm-gate0-minitaur repeatedly.
    Reap those on every poll so leaked compute dies within one timer cycle.
    """
    clauses = []
    if NEVER_START:
        names = " OR ".join(f"name={n}" for n in sorted(NEVER_START))
        clauses.append(f"({names})")
    clauses.append(f"labels.{DENY_LABEL_KEY}=true")
    clauses.append("labels.usersim-fleet~.*-retired")
    filt = f"({' OR '.join(clauses)}) AND (status=RUNNING OR status=STAGING OR status=PROVISIONING)"
    r = run(
        [
            "gcloud",
            "compute",
            "instances",
            "list",
            f"--project={project()}",
            f"--filter={filt}",
            "--format=json(name,zone,status,labels)",
        ],
        timeout=120,
    )
    if r.returncode != 0:
        log(f"reap list FAILED: {(r.stderr or r.stdout)[-300:]}")
        return []
    try:
        rows = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
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
                "labels": row.get("labels") or {},
            }
        )
    return out


def reap_denied() -> int:
    n = 0
    for inst in list_denied_running():
        reason = is_denied(inst) or "denied-running"
        log(f"REAP {inst['name']} status={inst['status']} ({reason})")
        close_session(inst["name"], why=f"reaped: {reason}")
        if stop_instance(inst):
            n += 1
    return n


def tick() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Drop any leftover sessions for denylisted names even if they are no
    # longer in the watched set — otherwise an old session file is confusing.
    for name in NEVER_START:
        close_session(name, why="denylisted")

    reaped = reap_denied()
    if reaped:
        log(f"reaped {reaped} denied instance(s)")

    watched = list_watched()
    if not watched:
        log(f"no instances with {LABEL_KEY}={LABEL_VALUE}")
        return 0

    down_like = {"TERMINATED", "STOPPED"}
    n_start = 0
    for inst in watched:
        name, status = inst["name"], inst["status"]
        deny = is_denied(inst)
        if deny:
            close_session(name, why=f"denied: {deny}")
            log(f"SKIP {name} ({deny}) status={status}")
            continue
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
    log(
        f"watchdog tick project={project()} label={LABEL_KEY}={LABEL_VALUE} "
        f"never_start={sorted(NEVER_START)}"
    )
    try:
        n = tick()
    except Exception as e:
        log(f"FATAL {type(e).__name__}: {e}")
        return 1
    log(f"watchdog done starts_attempted={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
