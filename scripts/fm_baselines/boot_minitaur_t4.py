#!/usr/bin/env python3
"""Boot Minitaur Psych-101 NLL on Colab T4 (MAX_SEQ=4096). Idempotent."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/content/fm_baselines")


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def main() -> None:
    import torch

    print("GPU", torch.cuda.get_device_name(0), round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1), flush=True)
    for d in [ROOT / "scripts", ROOT / "data", ROOT / "results" / "minitaur"]:
        d.mkdir(parents=True, exist_ok=True)

    runner = ROOT / "scripts" / "colab_minitaur_psych101_nll.py"
    if not runner.exists():
        raise SystemExit("missing colab_minitaur_psych101_nll.py")

    data = ROOT / "data" / "Psych-101-test" / "prompts_testing_t1.jsonl"
    if not data.exists():
        sh(f"{sys.executable} -m pip install -q -U 'huggingface_hub>=1.5.0'")
        sh(
            "hf buckets sync hf://buckets/shreyaspatel/Psych-101-test-bucket "
            "/content/fm_baselines/data/Psych-101-test"
        )
    print("rows", sum(1 for _ in open(data)), flush=True)

    for name in ("minitaur_full", "minitaur_smoke"):
        pid_p = ROOT / "results" / f"{name}.pid"
        if pid_p.exists():
            pid = pid_p.read_text().strip()
            if Path(f"/proc/{pid}").exists():
                print("ALREADY_RUNNING", name, pid, flush=True)
                return

    # Done?
    summary = ROOT / "results" / "minitaur" / "SUMMARY.json"
    if summary.exists() and summary.stat().st_size > 50:
        print("ALREADY_DONE", summary, flush=True)
        return

    log = ROOT / "results" / "minitaur_full.log"
    cmd = (
        "nohup env SMOKE_N=0 MAX_SEQ=4096 "
        f"python3 -u {runner} > {log} 2>&1 & echo $! > {ROOT}/results/minitaur_full.pid"
    )
    subprocess.run(["bash", "-lc", cmd], check=True)
    time.sleep(2)
    print("STARTED", (ROOT / "results" / "minitaur_full.pid").read_text().strip(), flush=True)


if __name__ == "__main__":
    main()
