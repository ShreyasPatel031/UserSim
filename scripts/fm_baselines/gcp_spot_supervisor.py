#!/usr/bin/env python3
"""Keep Gate-0 GCP Spot VMs alive across preemption.

Spot VMs with termination-action=STOP sit TERMINATED until something starts
them. Cursor chat ending must not be that something — run this under launchd.

Per poll:
  1. If instance is TERMINATED/STOPPED → gcloud compute instances start
  2. If RUNNING → SSH health check; if the worker PID is dead, relaunch via
     the on-VM systemd unit / hot-restart script

Jobs resume from disk checkpoints (predictions.shard*.jsonl, BeFM task dirs).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "results" / "fm_baselines"
LOG = LOCAL / "gcp_spot_supervisor.log"
POLL_SEC = int(__import__("os").environ.get("SPOT_POLL_SEC", "120"))
PROJECT = __import__("os").environ.get("GCP_PROJECT", "project-amer-scs-sandbox")


@dataclass(frozen=True)
class SpotJob:
    name: str
    zone: str
    # remote command that exits 0 iff the worker looks healthy
    health_cmd: str
    # remote command to (re)start the worker (idempotent)
    relaunch_cmd: str


JOBS = [
    SpotJob(
        name="fm-gate0-socrates-l4",
        zone="us-central1-a",
        health_cmd=(
            # Prefer systemd active state; fall back to shard process.
            "systemctl is-active --quiet usersim-socrates.service || "
            "pgrep -f '/opt/usersim_fm/scripts/socrates_vllm_shard.py' >/dev/null"
        ),
        relaunch_cmd=(
            "sudo systemctl reset-failed usersim-socrates.service 2>/dev/null; "
            "sudo systemctl restart usersim-socrates.service"
        ),
    ),
    SpotJob(
        name="fm-gate0-befm",
        zone="us-central1-b",
        health_cmd=(
            "test -f /opt/usersim_fm/results/befm_full.pid && "
            "ps -p $(cat /opt/usersim_fm/results/befm_full.pid) >/dev/null 2>&1"
        ),
        relaunch_cmd=(
            "sudo systemctl start usersim-befm.service 2>/dev/null || "
            "bash /opt/usersim_fm/hot_cutover_befm_vllm.sh 2>/dev/null || "
            "bash /tmp/hot_cutover_befm_vllm.sh"
        ),
    ),
    SpotJob(
        name="fm-gate0-minitaur",
        zone="us-central1-b",
        health_cmd=(
            "pgrep -f colab_minitaur_psych101_nll.py >/dev/null"
        ),
        relaunch_cmd=(
            "sudo systemctl start usersim-minitaur.service 2>/dev/null || "
            "bash /opt/usersim_fm/hot_restart_minitaur.sh 2>/dev/null || true"
        ),
    ),
]


def log(msg: str) -> None:
    LOCAL.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def gcloud(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    cmd = ["gcloud", *args, f"--project={PROJECT}"]
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def instance_status(job: SpotJob) -> str:
    r = gcloud(
        [
            "compute",
            "instances",
            "describe",
            job.name,
            f"--zone={job.zone}",
            "--format=value(status)",
        ],
        timeout=60,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if "was not found" in err or "NOT_FOUND" in err:
            return "MISSING"
        log(f"{job.name}: describe failed: {err[:200]}")
        return "UNKNOWN"
    return (r.stdout or "").strip() or "UNKNOWN"


def start_instance(job: SpotJob) -> bool:
    log(f"{job.name}: starting (was preempted/stopped)")
    r = gcloud(
        ["compute", "instances", "start", job.name, f"--zone={job.zone}", "--quiet"],
        timeout=300,
    )
    if r.returncode != 0:
        log(f"{job.name}: start FAILED: {(r.stderr or r.stdout or '')[:300]}")
        return False
    log(f"{job.name}: start requested OK")
    return True


def ssh(job: SpotJob, remote: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return gcloud(
        [
            "compute",
            "ssh",
            job.name,
            f"--zone={job.zone}",
            "--tunnel-through-iap",
            "--command",
            remote,
            "--quiet",
        ],
        timeout=timeout,
    )


def wait_ssh(job: SpotJob, tries: int = 18) -> bool:
    for i in range(1, tries + 1):
        r = ssh(job, "echo SSH_OK", timeout=45)
        if r.returncode == 0 and "SSH_OK" in (r.stdout or ""):
            return True
        log(f"{job.name}: waiting for SSH ({i}/{tries})")
        time.sleep(10)
    return False


def ensure_running(job: SpotJob) -> None:
    status = instance_status(job)
    log(f"{job.name}: status={status}")
    if status == "MISSING":
        log(f"{job.name}: VM missing — recreate manually / via launch_*.sh")
        return
    if status in {"TERMINATED", "STOPPED"}:
        if not start_instance(job):
            return
        # give boot + nvidia a moment
        time.sleep(30)
        status = instance_status(job)
    if status != "RUNNING":
        log(f"{job.name}: not RUNNING yet ({status}), will retry next poll")
        return
    if not wait_ssh(job):
        log(f"{job.name}: SSH unreachable after start")
        return
    h = ssh(job, job.health_cmd, timeout=60)
    if h.returncode == 0:
        log(f"{job.name}: worker healthy")
        return
    log(f"{job.name}: worker dead — relaunching")
    r = ssh(job, job.relaunch_cmd, timeout=120)
    if r.returncode != 0:
        log(f"{job.name}: relaunch rc={r.returncode} {(r.stderr or r.stdout or '')[:300]}")
    else:
        log(f"{job.name}: relaunch issued")
        time.sleep(15)
        h2 = ssh(job, job.health_cmd, timeout=60)
        log(f"{job.name}: post-relaunch healthy={h2.returncode == 0}")


def write_status(snapshot: dict) -> None:
    LOCAL.mkdir(parents=True, exist_ok=True)
    (LOCAL / "gcp_spot_status.json").write_text(json.dumps(snapshot, indent=2))


def once() -> None:
    snap = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "jobs": {}}
    for job in JOBS:
        try:
            ensure_running(job)
            snap["jobs"][job.name] = instance_status(job)
        except subprocess.TimeoutExpired:
            log(f"{job.name}: timeout")
            snap["jobs"][job.name] = "TIMEOUT"
        except Exception as e:
            log(f"{job.name}: exception {e}")
            snap["jobs"][job.name] = f"ERROR:{type(e).__name__}"
    write_status(snap)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll-sec", type=int, default=POLL_SEC)
    args = ap.parse_args()
    log(f"gcp_spot_supervisor start poll={args.poll_sec}s project={PROJECT}")
    if args.once:
        once()
        return
    while True:
        once()
        time.sleep(args.poll_sec)


if __name__ == "__main__":
    main()
