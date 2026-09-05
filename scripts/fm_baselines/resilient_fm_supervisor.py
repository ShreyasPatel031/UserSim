#!/usr/bin/env python3
"""Resilient Phase-0 FM baseline supervisor for Colab.

Modeled on ~/Centaur/colab_minitaur/resilient_binary_driver.py + launchd_supervisor.py.

Why this exists
---------------
Colab sessions go zombie: `sessions` still lists them, keep-alive dies, local
sessions.json is pruned, kernels 404. Cursor chat ending must NOT be what
keeps jobs alive — this process (ideally under launchd) owns that.

Hard rules (copied from the Minitaur driver that already works for you)
---------------------------------------------------------------------
1. Never trust `colab status` alone.
2. Probe filesystem (upload+download a canary) every poll.
3. Pull artifacts to LOCAL disk every poll (source of truth).
4. On zombie / stall / missing process: force-stop + respawn + resume.
5. Prefer T4; Socrates uses L4 (4-bit 14B more comfortable). Cap = 2 GPUs.
6. Centaur-70B is out of scope.

Jobs
----
- socrates  (L4): SocSci210 Wasserstein, resumes predictions.jsonl
- minitaur  (T4): Psych-101-test NLL, MAX_SEQ=4096
- befm      (T4): optional; 8-task subset already done — only if --with-befm

Usage
-----
  # one-shot forever loop (run under launchd / tmux, NOT only in Cursor)
  python3 -u scripts/fm_baselines/resilient_fm_supervisor.py

  # smoke health once
  python3 -u scripts/fm_baselines/resilient_fm_supervisor.py --once
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path("/Users/shreyaspatel/Desktop/Code/UserSim")
SCRIPTS = ROOT / "scripts" / "fm_baselines"
LOCAL = ROOT / "results" / "fm_baselines"
LOG = LOCAL / "supervisor.log"
AUTH = ["colab", "--auth=adc"]
POLL_SEC = 90
STALL_MIN = 45  # no artifact growth after grace
GRACE_MIN = 30  # allow model download/load
FS_PROBE = LOCAL / "_fs_probe.txt"


def log(msg: str) -> None:
    LOCAL.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def run(cmd: list[str], timeout: int | None = 120, input_text: str | None = None) -> subprocess.CompletedProcess:
    log("+ " + " ".join(cmd)[:200])
    return subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=timeout,
        input=input_text,
    )


@dataclass
class Job:
    name: str
    session: str
    gpus: list[str]
    # remote paths that prove the worker is alive / progressing
    remote_progress: str  # file whose size/mtime/linecount should grow
    remote_done: str | None  # if exists locally after pull, job finished
    local_dir: Path
    boot_py: Path  # local python that gets base64-pushed and sets up+launches nohup worker
    # optional: progress is line count of jsonl
    progress_is_lines: bool = False
    last_progress: float = 0.0
    last_change_ts: float = field(default_factory=time.time)
    started_ts: float = 0.0


def sessions_text() -> str:
    r = run(AUTH + ["sessions"], timeout=90)
    return ((r.stdout or "") + (r.stderr or "")).strip()


def status_text(session: str) -> str:
    r = run(AUTH + ["status", "-s", session], timeout=60)
    return ((r.stdout or "") + (r.stderr or "")).strip()


def filesystem_ok(session: str) -> bool:
    FS_PROBE.write_text(f"ok {time.time()}\n")
    r = run(
        AUTH + ["upload", "-s", session, str(FS_PROBE), "/content/_fs_probe.txt"],
        timeout=90,
    )
    if r.returncode != 0:
        return False
    out = LOCAL / f"_fs_probe.{session}.remote.txt"
    if out.exists():
        out.unlink()
    r = run(
        AUTH + ["download", "-s", session, "/content/_fs_probe.txt", str(out)],
        timeout=90,
    )
    return r.returncode == 0 and out.exists()


def session_healthy(session: str) -> bool:
    st = status_text(session).lower()
    if "not found" in st or not st:
        # also check sessions list
        if session not in sessions_text():
            return False
    if "not found" in st:
        return False
    if not filesystem_ok(session):
        log(f"{session}: status may look ok but filesystem DEAD (zombie)")
        return False
    return True


def force_stop(session: str) -> None:
    run(AUTH + ["stop", "-s", session], timeout=90)
    # also try to reap orphans matching known endpoints later if needed
    time.sleep(4)


def ensure_session(job: Job) -> str:
    if session_healthy(job.session):
        st = status_text(job.session)
        log(f"{job.session} healthy: " + st.replace("\n", " | ")[:200])
        for g in job.gpus:
            if g.lower() in st.lower():
                return g
        return job.gpus[0]
    log(f"{job.session} unhealthy — respawning")
    force_stop(job.session)
    attempt = 0
    while True:
        attempt += 1
        gpu = job.gpus[(attempt - 1) % len(job.gpus)]
        r = run(AUTH + ["new", "-s", job.session, "--gpu", gpu], timeout=300)
        out = ((r.stdout or "") + (r.stderr or ""))[-800:]
        log(out)
        if "TooManyAssignments" in out or "Precondition Failed" in out:
            log("GPU quota full — waiting 60s")
            time.sleep(60)
            continue
        # entitlement / wrong accelerator → rotate immediately
        if "rejected accelerator" in out.lower() or "not have quota" in out.lower():
            log(f"{job.session}: {gpu} unavailable — trying next")
            time.sleep(2)
            continue
        if "Service Unavailable" in out or "ColabRequestError" in out:
            log(f"{job.session}: assign {gpu} flaky — retry in 30s")
            time.sleep(30)
            continue
        if r.returncode == 0 and session_healthy(job.session):
            log(f"{job.session} got GPU={gpu}")
            return gpu
        time.sleep(min(30 * attempt, 300))


def _runners_for(job: Job) -> list[Path]:
    """Boot + eval scripts that must exist under /content/fm_baselines/scripts/."""
    mapping = {
        "socrates": ["boot_socrates_l4.py", "colab_socrates_wass.py"],
        "minitaur": ["boot_minitaur_t4.py", "colab_minitaur_psych101_nll.py"],
        "befm": ["boot_befm_t4.py", "colab_befm4b_serve_and_eval.py"],
    }
    out: list[Path] = []
    for name in mapping.get(job.name, [job.boot_py.name]):
        p = SCRIPTS / name
        if p.exists():
            out.append(p)
    if job.boot_py not in out and job.boot_py.exists():
        out.append(job.boot_py)
    return out


def push_and_boot(job: Job) -> None:
    """Push boot + runners via base64 exec (upload often SSL-fails on large files)."""
    job.local_dir.mkdir(parents=True, exist_ok=True)
    files = _runners_for(job)
    if not files:
        raise RuntimeError(f"no boot/runner scripts found for {job.name}")

    writes = []
    for p in files:
        b64 = base64.b64encode(p.read_bytes()).decode()
        remote = f"/content/fm_baselines/scripts/{p.name}"
        writes.append(
            f"Path({remote!r}).write_bytes(base64.b64decode('{b64}'))\n"
            f"print('WROTE', {remote!r}, Path({remote!r}).stat().st_size, flush=True)"
        )
    boot_remote = f"/content/fm_baselines/scripts/{job.boot_py.name}"
    code = (
        "import base64, subprocess, sys\n"
        "from pathlib import Path\n"
        "Path('/content/fm_baselines/scripts').mkdir(parents=True, exist_ok=True)\n"
        "Path('/content/fm_baselines/results').mkdir(parents=True, exist_ok=True)\n"
        + "\n".join(writes)
        + f"\nsubprocess.check_call([sys.executable, '-u', {boot_remote!r}])\n"
    )
    r = run(
        AUTH + ["exec", "-s", job.session, "--timeout", "600"],
        timeout=720,
        input_text=code,
    )
    log(((r.stdout or "") + (r.stderr or ""))[-2000:])
    if r.returncode != 0:
        raise RuntimeError(f"boot failed for {job.name}: rc={r.returncode}")
    job.started_ts = time.time()
    job.last_change_ts = time.time()


def pull_progress(job: Job) -> float:
    """Pull remote progress file; return numeric progress (bytes or lines)."""
    job.local_dir.mkdir(parents=True, exist_ok=True)
    local_path = job.local_dir / Path(job.remote_progress).name
    r = run(
        AUTH
        + [
            "download",
            "-s",
            job.session,
            job.remote_progress,
            str(local_path),
        ],
        timeout=180,
    )
    if r.returncode != 0 or not local_path.exists():
        # try exec wc as fallback
        code = f"""
from pathlib import Path
p=Path({job.remote_progress!r})
print('EXISTS', p.exists())
if p.exists():
  print('BYTES', p.stat().st_size)
  if p.suffix=='.jsonl':
    print('LINES', sum(1 for _ in open(p) if _.strip()))
"""
        r2 = run(
            AUTH + ["exec", "-s", job.session, "--timeout", "60"],
            timeout=90,
            input_text=code,
        )
        out = (r2.stdout or "") + (r2.stderr or "")
        if "LINES" in out:
            for line in out.splitlines():
                if line.startswith("LINES"):
                    return float(line.split()[1])
        if "BYTES" in out:
            for line in out.splitlines():
                if line.startswith("BYTES"):
                    return float(line.split()[1])
        return job.last_progress

    if job.progress_is_lines:
        return float(sum(1 for l in local_path.read_text().splitlines() if l.strip()))
    return float(local_path.stat().st_size)


def job_done(job: Job) -> bool:
    if not job.remote_done:
        return False
    local_done = job.local_dir / Path(job.remote_done).name
    # try pull done marker
    run(
        AUTH + ["download", "-s", job.session, job.remote_done, str(local_done)],
        timeout=120,
    )
    if local_done.exists() and local_done.stat().st_size > 0:
        return True
    # also check pulled SUMMARY content for socrates/minitaur
    if local_done.exists():
        try:
            d = json.loads(local_done.read_text())
            if "wasserstein_mean" in d or "total_nll_sum" in d or "tasks" in d:
                return True
        except Exception:
            pass
    return False


def worker_alive(job: Job) -> bool:
    code = f"""
import os
from pathlib import Path
for name in {json.dumps([job.name + '_smoke', job.name + '_full', job.name + '_run', 'minitaur_full', 'socrates_smoke', 'socrates_full', 'befm_run'])}:
  p=Path('/content/fm_baselines/results')/f'{{name}}.pid'
  if p.exists():
    pid=p.read_text().strip()
    print(name, 'alive', os.path.exists(f'/proc/{{pid}}'), 'pid', pid)
"""
    # simpler dedicated probe per job type:
    probes = {
        "socrates": ["socrates_smoke", "socrates_full"],
        "minitaur": ["minitaur_full", "minitaur_smoke"],
        "befm": ["befm_run"],
    }
    names = probes.get(job.name, [job.name])
    code = f"""
import os
from pathlib import Path
alive=False
for name in {names!r}:
  p=Path('/content/fm_baselines/results')/f'{{name}}.pid'
  if p.exists():
    pid=p.read_text().strip()
    a=os.path.exists(f'/proc/{{pid}}')
    print(name, a, pid)
    alive = alive or a
print('ANY_ALIVE', alive)
"""
    r = run(
        AUTH + ["exec", "-s", job.session, "--timeout", "45"],
        timeout=70,
        input_text=code,
    )
    out = (r.stdout or "") + (r.stderr or "")
    log(out[-500:])
    return "ANY_ALIVE True" in out


def tick(job: Job) -> None:
    if job_done(job):
        log(f"{job.name}: DONE (local marker present)")
        return

    gpu = ensure_session(job)

    # if worker dead, boot
    try:
        alive = worker_alive(job)
    except Exception as e:
        log(f"{job.name}: worker probe failed: {e}")
        alive = False

    if not alive:
        log(f"{job.name}: worker dead — booting on {gpu}")
        push_and_boot(job)
        return

    # pull progress
    try:
        prog = pull_progress(job)
    except Exception as e:
        log(f"{job.name}: pull failed: {e}")
        prog = job.last_progress

    now = time.time()
    if prog > job.last_progress:
        log(f"{job.name}: progress {job.last_progress} -> {prog}")
        job.last_progress = prog
        job.last_change_ts = now
        return

    # stall detection
    age_min = (now - job.last_change_ts) / 60.0
    since_start = (now - job.started_ts) / 60.0 if job.started_ts else 999
    if since_start < GRACE_MIN:
        log(f"{job.name}: in grace ({since_start:.0f}m), progress={prog}")
        return
    if age_min >= STALL_MIN:
        log(f"{job.name}: STALLED {age_min:.0f}m — force stop + respawn")
        force_stop(job.session)
        job.last_change_ts = now
        return
    log(f"{job.name}: alive, no growth yet ({age_min:.0f}m / stall={STALL_MIN}m)")


def make_jobs(with_befm: bool) -> list[Job]:
    jobs = [
        Job(
            name="socrates",
            session="fm-socrates",
            # Prefer T4 — this Colab account often rejects L4 entitlement
            gpus=["T4", "L4"],
            remote_progress="/content/fm_baselines/results/socrates/predictions.jsonl",
            remote_done="/content/fm_baselines/results/socrates/SUMMARY.json",
            local_dir=LOCAL / "socrates",
            boot_py=SCRIPTS / "boot_socrates_l4.py",
            progress_is_lines=True,
        ),
        Job(
            name="minitaur",
            session="fm-minitaur",
            gpus=["T4", "L4"],
            remote_progress="/content/fm_baselines/results/minitaur/PROGRESS.json",
            remote_done="/content/fm_baselines/results/minitaur/SUMMARY.json",
            local_dir=LOCAL / "minitaur",
            boot_py=SCRIPTS / "boot_minitaur_t4.py",
            progress_is_lines=False,
        ),
    ]
    if with_befm:
        jobs.append(
            Job(
                name="befm",
                session="fm-befm",
                gpus=["T4", "L4"],
                remote_progress="/content/fm_baselines/results/befm4b/DONE.json",
                remote_done="/content/fm_baselines/results/befm4b/DONE.json",
                local_dir=LOCAL / "befm4b",
                boot_py=SCRIPTS / "boot_befm_t4.py",
            )
        )
    return jobs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--with-befm", action="store_true", help="also babysit BeFM (uses 3rd GPU if quota allows)")
    ap.add_argument("--poll", type=int, default=POLL_SEC)
    args = ap.parse_args()

    jobs = make_jobs(with_befm=args.with_befm)
    log(f"SUPERVISOR_START jobs={[j.name for j in jobs]}")

    while True:
        for job in jobs:
            if job_done(job):
                continue
            try:
                tick(job)
            except Exception as e:
                log(f"{job.name} ERROR: {type(e).__name__}: {e}")
                try:
                    if not session_healthy(job.session):
                        force_stop(job.session)
                except Exception:
                    pass
        if all(job_done(j) for j in jobs):
            log("ALL_JOBS_DONE")
            break
        if args.once:
            break
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
