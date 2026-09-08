#!/usr/bin/env python3
"""Boot Qwen3-8B-Base BehaviorBench SFT pilot on GCP/Colab. Idempotent + resume.

Expects corpus at $ROOT/data/fm_train/pilot_corpus.jsonl (synced from repo) and
writes adapter to $ROOT/adapters/qwen3_8b_base_pilot/.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
if not ROOT.exists():
    ROOT = Path("/content/fm_baselines")


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def main() -> None:
    import torch

    print(
        "GPU",
        torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
        if torch.cuda.is_available()
        else 0,
        flush=True,
    )

    for d in [
        ROOT / "scripts",
        ROOT / "data" / "fm_train",
        ROOT / "adapters" / "qwen3_8b_base_pilot",
        ROOT / "results" / "qwen3_8b_base_pilot",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    runner = ROOT / "scripts" / "sft_qwen3_8b_base_pilot.py"
    if not runner.exists():
        # Fall back to repo-relative copy if boot is run from UserSim checkout.
        alt = Path(__file__).resolve().parent / "sft_qwen3_8b_base_pilot.py"
        if alt.exists():
            sh(f"cp {alt} {runner}")
        else:
            raise SystemExit(f"missing trainer at {runner}")

    corpus = ROOT / "data" / "fm_train" / "pilot_corpus.jsonl"
    if not corpus.exists():
        raise SystemExit(f"missing corpus {corpus} — sync data/fm_train/pilot_corpus.jsonl first")

    out = ROOT / "adapters" / "qwen3_8b_base_pilot"
    done = out / "TRAIN_DONE.json"
    if done.exists() and done.stat().st_size > 20:
        print("ALREADY_DONE", done, flush=True)
        return

    pid_p = ROOT / "results" / "pilot_sft.pid"
    if pid_p.exists():
        pid = pid_p.read_text().strip()
        if pid.isdigit() and Path(f"/proc/{pid}").exists():
            print("ALREADY_RUNNING", pid, flush=True)
            return

    # Light deps; unsloth preferred but peft fallback works.
    sh(
        f"{sys.executable} -m pip install -q -U 'trl>=0.9' peft bitsandbytes "
        "datasets accelerate transformers"
    )

    log = ROOT / "results" / "pilot_sft.log"
    env = (
        f"PILOT_DATA={corpus} PILOT_OUT={out} "
        f"FLOOR_MODEL=Qwen/Qwen3-8B-Base "
        f"MICRO_BATCH={os.environ.get('MICRO_BATCH', '2')} "
        f"GRAD_ACCUM={os.environ.get('GRAD_ACCUM', '64')} "
        f"MAX_SEQ={os.environ.get('MAX_SEQ', '2048')}"
    )
    cmd = (
        f"nohup env {env} {sys.executable} -u {runner} "
        f"> {log} 2>&1 & echo $! > {pid_p}"
    )
    subprocess.run(["bash", "-lc", cmd], check=True)
    time.sleep(2)
    print("STARTED", pid_p.read_text().strip(), "log", log, flush=True)


if __name__ == "__main__":
    main()
