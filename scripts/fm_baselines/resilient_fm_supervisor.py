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

ROOT = Path(os.environ.get("USERSIM_ROOT", Path(__file__).resolve().parents[2]))
SCRIPTS = ROOT / "scripts" / "fm_baselines"
LOCAL = ROOT / "results" / "fm_baselines"
LOG = LOCAL / "supervisor.log"
AUTH = ["colab", "--auth=adc"]
POLL_SEC = 60
STALL_MIN = 25  # no real progress after grace → force stop + respawn
GRACE_MIN = 25  # allow model download/load
FS_PROBE = LOCAL / "_fs_probe.txt"


def log(msg: str) -> None:
    LOCAL.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def run(cmd: list[str], timeout: int | None = 120, input_text: str | None = None) -> subprocess.CompletedProcess:
    """Run a command; on timeout hard-kill the process group.

    colab CLI has hung past subprocess.run(..., timeout=N) before (SIGTERM
    ignored). That froze this supervisor for hours while Colab died. Always
    start a new session group and SIGKILL on timeout.
    """
    log("+ " + " ".join(cmd)[:200])
    if timeout is None:
        return subprocess.run(cmd, text=True, capture_output=True, input=input_text)
    proc = subprocess.Popen(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if input_text is not None else None,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(input=input_text, timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        log(f"TIMEOUT {timeout}s — SIGKILL process group for: {' '.join(cmd)[:120]}")
        try:
            os.killpg(proc.pid, 9)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            out, err = proc.communicate(timeout=5)
        except Exception:
            out, err = "", ""
        return subprocess.CompletedProcess(cmd, 124, out or "", (err or "") + f"\nTIMEOUT:{timeout}s\n")


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
    # resume artifacts pulled every poll and re-pushed on boot (survive Colab death)
    remote_resume: list[str] = field(default_factory=list)
    last_progress: float = 0.0
    last_change_ts: float = field(default_factory=time.time)
    started_ts: float = 0.0
    consecutive_cmd_timeouts: int = 0


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
        # entitlement / capacity: keep retrying (esp. L4-only floor jobs)
        if "rejected accelerator" in out.lower() or "not have quota" in out.lower():
            wait = min(30 + 15 * (attempt - 1), 300)
            log(f"{job.session}: {gpu} unavailable — retry in {wait}s (attempt {attempt})")
            time.sleep(wait)
            continue
        if "Service Unavailable" in out or "ColabRequestError" in out:
            wait = min(30 * attempt, 300)
            log(f"{job.session}: assign {gpu} flaky — retry in {wait}s (attempt {attempt})")
            time.sleep(wait)
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
        "floor_psych101": [
            "boot_qwen3_floor_psych101.py",
            "colab_qwen3_8b_floor_psych101_nll.py",
        ],
        "floor_socrates": [
            "boot_qwen3_floor_socrates.py",
            "colab_qwen3_8b_floor_socrates_vllm.py",
        ],
        "floor_befm": [
            "boot_qwen3_floor_befm.py",
            "colab_qwen3_8b_floor_befm.py",
            "protocol.py",
            "run_qwen_befm_colab.sh",
        ],
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

    # Restore resume artifacts from local disk before boot (Colab disk dies with the session).
    for remote in job.remote_resume:
        local = job.local_dir / Path(remote).name
        if local.exists() and local.stat().st_size > 0:
            r = run(
                AUTH + ["upload", "-s", job.session, str(local), remote],
                timeout=180,
            )
            log(f"restore {local.name} -> {remote} rc={r.returncode} bytes={local.stat().st_size}")

    writes = []
    for p in files:
        b64 = base64.b64encode(p.read_bytes()).decode()
        remote = f"/content/fm_baselines/scripts/{p.name}"
        writes.append(
            f"Path({remote!r}).write_bytes(base64.b64decode('{b64}'))\n"
            f"print('WROTE', {remote!r}, Path({remote!r}).stat().st_size, flush=True)"
        )
    boot_remote = f"/content/fm_baselines/scripts/{job.boot_py.name}"
    hf = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or ""
    hf_setup = ""
    if hf:
        hf_setup = (
            "import os\n"
            f"os.environ['HF_TOKEN']={hf!r}\n"
            "os.environ['HUGGING_FACE_HUB_TOKEN']=os.environ['HF_TOKEN']\n"
            "p=Path.home()/'.cache'/'huggingface'\n"
            "p.mkdir(parents=True, exist_ok=True)\n"
            "(p/'token').write_text(os.environ['HF_TOKEN'])\n"
            "print('hf_ok', flush=True)\n"
        )
    code = (
        "import base64, subprocess, sys\n"
        "from pathlib import Path\n"
        "Path('/content/fm_baselines/scripts').mkdir(parents=True, exist_ok=True)\n"
        "Path('/content/fm_baselines/results').mkdir(parents=True, exist_ok=True)\n"
        + hf_setup
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
    job.consecutive_cmd_timeouts = 0


def _progress_from_file(path: Path, progress_is_lines: bool) -> float | None:
    if not path.exists() or path.stat().st_size <= 0:
        return None
    if progress_is_lines or path.suffix == ".jsonl":
        return float(sum(1 for l in path.read_text().splitlines() if l.strip()))
    # PROGRESS.json / similar — prefer scored count, never raw byte size
    try:
        d = json.loads(path.read_text())
        if isinstance(d, dict):
            for key in ("scored", "n_preds", "done_n", "n_done"):
                if key in d and d[key] is not None:
                    return float(d[key])
            done = d.get("done")
            if isinstance(done, list):
                return float(len(done))
    except Exception:
        pass
    return None


def pull_resume_artifacts(job: Job) -> None:
    """Copy resume files to local disk every poll so a dead Colab does not erase work."""
    for remote in job.remote_resume:
        local = job.local_dir / Path(remote).name
        tmp = local.with_suffix(local.suffix + ".pull")
        r = run(
            AUTH + ["download", "-s", job.session, remote, str(tmp)],
            timeout=180,
        )
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(local)
        else:
            if tmp.exists():
                tmp.unlink()
            # Do not delete a good local resume copy on a flaky download — but
            # never invent progress from a stale local when remote is gone.
            if r.returncode == 124:
                job.consecutive_cmd_timeouts += 1


def pull_progress(job: Job) -> float:
    """Pull remote progress; return a monotonic numeric score (items/lines), never bytes."""
    job.local_dir.mkdir(parents=True, exist_ok=True)
    pull_resume_artifacts(job)

    local_path = job.local_dir / Path(job.remote_progress).name
    tmp = local_path.with_suffix(local_path.suffix + ".pull")
    r = run(
        AUTH
        + [
            "download",
            "-s",
            job.session,
            job.remote_progress,
            str(tmp),
        ],
        timeout=120,
    )
    if r.returncode == 124:
        job.consecutive_cmd_timeouts += 1
        log(f"{job.name}: progress download timed out ({job.consecutive_cmd_timeouts})")
        if tmp.exists():
            tmp.unlink()
        return job.last_progress

    remote_ok = r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0
    if remote_ok:
        tmp.replace(local_path)
        job.consecutive_cmd_timeouts = 0
    else:
        if tmp.exists():
            tmp.unlink()

    parsed = _progress_from_file(local_path, job.progress_is_lines) if remote_ok else None
    if parsed is not None:
        return parsed

    # Prefer freshly pulled resume artifact line count
    if remote_ok or job.remote_resume:
        for remote in job.remote_resume:
            local = job.local_dir / Path(remote).name
            # only trust resume files that were updated this poll (mtime recent)
            if not local.exists():
                continue
            age = time.time() - local.stat().st_mtime
            if age > 180:
                continue
            n = _progress_from_file(local, progress_is_lines=True)
            if n is not None:
                job.consecutive_cmd_timeouts = 0
                return n

    if not remote_ok:
        code = f"""
from pathlib import Path
import json
p=Path({job.remote_progress!r})
print('EXISTS', p.exists())
if p.exists():
  if p.suffix=='.jsonl':
    print('LINES', sum(1 for _ in open(p) if _.strip()))
  else:
    try:
      d=json.loads(p.read_text())
      print('SCORED', d.get('scored', d.get('n_preds', -1)))
    except Exception:
      print('BYTES', p.stat().st_size)
for rel in {job.remote_resume!r}:
  q=Path(rel)
  if q.exists() and q.suffix=='.jsonl':
    print('RESUME_LINES', sum(1 for _ in open(q) if _.strip()))
"""
        r2 = run(
            AUTH + ["exec", "-s", job.session, "--timeout", "45"],
            timeout=70,
            input_text=code,
        )
        if r2.returncode == 124:
            job.consecutive_cmd_timeouts += 1
        out = (r2.stdout or "") + (r2.stderr or "")
        for line in out.splitlines():
            if line.startswith("LINES") or line.startswith("SCORED") or line.startswith("RESUME_LINES"):
                try:
                    val = float(line.split()[1])
                    if val >= 0:
                        return val
                except Exception:
                    pass
        # Remote missing: live progress is 0, keep last_progress for stall math only
        log(f"{job.name}: remote progress missing; not using stale local")
        return 0.0 if job.last_progress == 0 else job.last_progress

    return job.last_progress


def job_done(job: Job) -> bool:
    if not job.remote_done:
        return False
    local_done = job.local_dir / Path(job.remote_done).name
    # Prefer already-pulled local marker; only hit the network briefly.
    r = run(
        AUTH + ["download", "-s", job.session, job.remote_done, str(local_done)],
        timeout=60,
    )
    if r.returncode == 124:
        job.consecutive_cmd_timeouts += 1
        return False
    if local_done.exists() and local_done.stat().st_size > 0:
        try:
            d = json.loads(local_done.read_text())
            if isinstance(d, dict):
                if "complete" in d:
                    return bool(d.get("complete"))
                cov = d.get("coverage") or {}
                if isinstance(cov, dict) and "complete" in cov:
                    return bool(cov.get("complete"))
                if d.get("mode") == "smoke" or d.get("smoke_studies"):
                    return False
                # Legacy summaries without an explicit complete flag: not done.
                return False
        except Exception:
            return False
    return False


def worker_alive(job: Job) -> bool:
    probes = {
        "socrates": ["socrates_smoke", "socrates_full"],
        "minitaur": ["minitaur_full", "minitaur_smoke"],
        "befm": ["befm_run"],
        "floor_psych101": ["floor_psych101_full"],
        "floor_socrates": ["floor_socrates_full"],
        "floor_befm": ["floor_befm_full"],
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
        AUTH + ["exec", "-s", job.session, "--timeout", "30"],
        timeout=50,
        input_text=code,
    )
    out = (r.stdout or "") + (r.stderr or "")
    log(out[-500:])
    if r.returncode == 124:
        job.consecutive_cmd_timeouts += 1
        log(f"{job.name}: worker probe timed out ({job.consecutive_cmd_timeouts})")
        return job.consecutive_cmd_timeouts < 3
    if "ANY_ALIVE True" in out:
        job.consecutive_cmd_timeouts = 0
        return True
    return False


def tick(job: Job) -> None:
    if job_done(job):
        log(f"{job.name}: DONE (local marker present)")
        return

    # Repeated hard timeouts ⇒ treat session as dead even if status lies.
    if job.consecutive_cmd_timeouts >= 3:
        log(f"{job.name}: {job.consecutive_cmd_timeouts} cmd timeouts — force stop + respawn")
        force_stop(job.session)
        job.consecutive_cmd_timeouts = 0
        job.last_change_ts = time.time()
        return

    gpu = ensure_session(job)

    try:
        alive = worker_alive(job)
    except Exception as e:
        log(f"{job.name}: worker probe failed: {e}")
        alive = False

    if not alive:
        log(f"{job.name}: worker dead — booting on {gpu}")
        push_and_boot(job)
        return

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
    log(f"{job.name}: alive, no growth yet ({age_min:.0f}m / stall={STALL_MIN}m) progress={prog}")


def _floor_psych101_job() -> Job:
    return Job(
        name="floor_psych101",
        session="fm-floor-psych101",
        gpus=["T4"],
        remote_progress="/content/fm_baselines/results/qwen3_8b_floor_psych101/PROGRESS.json",
        remote_done="/content/fm_baselines/results/qwen3_8b_floor_psych101/SUMMARY.json",
        local_dir=LOCAL / "qwen3_8b_floor_psych101",
        boot_py=SCRIPTS / "boot_qwen3_floor_psych101.py",
        progress_is_lines=False,
        remote_resume=[
            "/content/fm_baselines/results/qwen3_8b_floor_psych101/scores.jsonl",
            "/content/fm_baselines/results/qwen3_8b_floor_psych101/SMOKE_OK.json",
            "/content/fm_baselines/results/qwen3_8b_floor_psych101/PROGRESS.json",
        ],
    )


def _floor_socrates_job() -> Job:
    return Job(
        name="floor_socrates",
        session="fm-floor-socrates",
        gpus=["T4"],
        remote_progress="/content/fm_baselines/results/qwen3_8b_floor_socrates/predictions.jsonl",
        remote_done="/content/fm_baselines/results/qwen3_8b_floor_socrates/SUMMARY.json",
        local_dir=LOCAL / "qwen3_8b_floor_socrates",
        boot_py=SCRIPTS / "boot_qwen3_floor_socrates.py",
        progress_is_lines=True,
        remote_resume=[
            "/content/fm_baselines/results/qwen3_8b_floor_socrates/predictions.jsonl",
            "/content/fm_baselines/results/qwen3_8b_floor_socrates/SMOKE_OK.json",
            "/content/fm_baselines/results/qwen3_8b_floor_socrates/PROGRESS.json",
        ],
    )


def make_jobs(
    with_befm: bool,
    floor: bool = False,
    floor_befm: bool = False,
    floor_psych101: bool = False,
    floor_socrates: bool = False,
    floor_remaining: bool = False,
) -> list[Job]:
    if floor_remaining or floor:
        # Remaining Colab floors, one T4 at a time (2nd GPU assign 412s).
        # Psych-101 first, then Socrates. Be.FM stays on the GCP L4.
        return [_floor_psych101_job(), _floor_socrates_job()]
    if floor_socrates:
        return [_floor_socrates_job()]
    if floor_psych101:
        return [_floor_psych101_job()]
    if floor_befm:
        # One L4 only. Do not also start psych101/socrates on a second GPU.
        return [
            Job(
                name="floor_befm",
                session="fm-floor-befm",
                gpus=["L4"],
                remote_progress="/content/fm_baselines/results/qwen3_8b_base_befm/PROGRESS.json",
                remote_done="/content/fm_baselines/results/qwen3_8b_base_befm/SUMMARY.json",
                local_dir=LOCAL / "qwen3_8b_base_befm",
                boot_py=SCRIPTS / "boot_qwen3_floor_befm.py",
                progress_is_lines=False,
            )
        ]
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
    ap.add_argument(
        "--floor",
        action="store_true",
        help="Qwen3-8B-Base floor on Psych-101 NLL + Socrates W (not baseline models)",
    )
    ap.add_argument(
        "--floor-befm",
        action="store_true",
        help="One Colab L4: remaining Qwen3-8B-Base BehaviorBench floor (smoke+vLLM+watchdog)",
    )
    ap.add_argument(
        "--floor-psych101",
        action="store_true",
        help="One Colab T4: Qwen3-8B-Base Psych-101 NLL floor (smoke+watchdog). T4 cannot host 8B vLLM bf16.",
    )
    ap.add_argument(
        "--floor-socrates",
        action="store_true",
        help="One Colab T4: Qwen3-8B-Base Socrates Wasserstein floor (vLLM 4-bit, smoke+watchdog).",
    )
    ap.add_argument(
        "--floor-remaining",
        action="store_true",
        help="Remaining Colab floors, one T4 at a time: Psych-101 then Socrates. Be.FM stays on GCP.",
    )
    ap.add_argument("--poll", type=int, default=POLL_SEC)
    args = ap.parse_args()

    jobs = make_jobs(
        with_befm=args.with_befm,
        floor=args.floor,
        floor_befm=args.floor_befm,
        floor_psych101=args.floor_psych101,
        floor_socrates=args.floor_socrates,
        floor_remaining=args.floor_remaining,
    )
    # This Colab identity 412s a second T4. Run remaining floors one GPU at a time.
    sequential = bool(args.floor_remaining or args.floor)
    log(f"SUPERVISOR_START jobs={[j.name for j in jobs]} sequential={sequential}")

    prev_name: str | None = None
    while True:
        try:
            pending = [j for j in jobs if not job_done(j)]
        except Exception as e:
            log(f"job_done sweep ERROR: {type(e).__name__}: {e}")
            time.sleep(args.poll)
            continue
        if not pending:
            log("ALL_JOBS_DONE")
            break
        to_run = [pending[0]] if sequential else pending
        if sequential and prev_name and prev_name != to_run[0].name:
            old = next(j for j in jobs if j.name == prev_name)
            log(f"sequential: freeing {old.session} before starting {to_run[0].name}")
            try:
                force_stop(old.session)
            except Exception as e:
                log(f"stop {old.session} failed: {e}")
        for job in to_run:
            try:
                tick(job)
            except Exception as e:
                log(f"{job.name} ERROR: {type(e).__name__}: {e}")
                job.consecutive_cmd_timeouts += 1
                try:
                    if job.consecutive_cmd_timeouts >= 3 or not session_healthy(job.session):
                        force_stop(job.session)
                        job.consecutive_cmd_timeouts = 0
                except Exception:
                    pass
        prev_name = to_run[0].name
        if args.once:
            break
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
