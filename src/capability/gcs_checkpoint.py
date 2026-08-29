"""Incremental GCS checkpoints so Spot preemption can resume mid-shard.

Progress used to live only on the VM disk and was uploaded once at shard end.
A Spot kill wiped that disk; --relaunch then started cold even with --resume.

Env:
  CAPABILITY_GCS_CHECKPOINT  gs://bucket/stage/tag   (shard uploads under
                             manifests/ and traces/shard{N}/)
  CAPABILITY_SHARD_ID        integer shard index (for traces path)
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def checkpoint_root() -> str | None:
    raw = (os.environ.get("CAPABILITY_GCS_CHECKPOINT") or "").strip().rstrip("/")
    return raw or None


def shard_id() -> str | None:
    raw = (os.environ.get("CAPABILITY_SHARD_ID") or "").strip()
    return raw if raw != "" else None


def _run_gcloud(args: list[str], *, quiet: bool = True) -> bool:
    cmd = ["gcloud", "storage", *args]
    if quiet and "--quiet" not in cmd:
        cmd.append("--quiet")
    try:
        subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"WARN gcs checkpoint failed: {exc}", flush=True)
        return False


def restore_manifest(local_path: Path) -> bool:
    """Pull prior shard manifest from GCS if present. Returns True if restored."""
    root = checkpoint_root()
    if not root:
        return False
    remote = f"{root}/manifests/{local_path.name}"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["gcloud", "storage", "cp", remote, str(local_path), "--quiet"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode == 0 and local_path.is_file():
        print(f"Restored checkpoint: {remote} -> {local_path.name}", flush=True)
        return True
    return False


def restore_traces(local_traces_dir: Path) -> int:
    """Pull prior trace dirs for this shard. Returns count of restored run.json files."""
    root = checkpoint_root()
    sid = shard_id()
    if not root or sid is None:
        return 0
    remote = f"{root}/traces/shard{sid}"
    local_traces_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["gcloud", "storage", "rsync", "--recursive", remote, str(local_traces_dir), "--quiet"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    n = sum(1 for _ in local_traces_dir.glob("**/run.json"))
    if n:
        print(f"Restored {n} trace run.json from {remote}", flush=True)
    return n


def upload_manifest(local_path: Path) -> bool:
    root = checkpoint_root()
    if not root or not local_path.is_file():
        return False
    remote = f"{root}/manifests/{local_path.name}"
    ok = _run_gcloud(["cp", str(local_path), remote])
    if ok:
        print(f"Checkpointed manifest -> {remote}", flush=True)
    return ok


def upload_trace_dir(trace_dir: Path | str | None) -> bool:
    """Upload one task's trace directory (best-effort, after each completion)."""
    root = checkpoint_root()
    sid = shard_id()
    if not root or sid is None or not trace_dir:
        return False
    path = Path(trace_dir)
    if not path.is_dir():
        return False
    remote = f"{root}/traces/shard{sid}/{path.name}"
    return _run_gcloud(["cp", "--recursive", str(path), remote])
