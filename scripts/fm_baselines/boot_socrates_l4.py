#!/usr/bin/env python3
"""Boot Socrates full (or resume) on Colab L4. Idempotent."""
from __future__ import annotations

import base64
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/content/fm_baselines")
SCRIPT_LOCAL_B64 = None  # filled by wrapper; or re-fetch from HF env


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def main() -> None:
    import torch

    print("GPU", torch.cuda.get_device_name(0), round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1), flush=True)
    for d in [
        ROOT / "scripts",
        ROOT / "data" / "SocSci210_meta" / "metadata",
        ROOT / "results" / "socrates",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # Expect colab_socrates_wass.py already present OR written beside this boot by supervisor.
    # Supervisor pushes both via a combined boot — see boot_socrates_bundle below.
    runner = ROOT / "scripts" / "colab_socrates_wass.py"
    if not runner.exists():
        raise SystemExit("missing colab_socrates_wass.py — supervisor must push it first")

    # mapping
    mapping = ROOT / "data" / "SocSci210_meta" / "metadata" / "participant_mapping.json"
    if not mapping.exists():
        sh(f"{sys.executable} -m pip install -q -U 'huggingface_hub>=1.5.0'")
        from huggingface_hub import hf_hub_download

        path = hf_hub_download(
            "socratesft/SocSci210",
            "metadata/participant_mapping.json",
            repo_type="dataset",
        )
        mapping.write_bytes(Path(path).read_bytes())

    # If a worker already alive, do nothing
    for name in ("socrates_full", "socrates_smoke"):
        pid_p = ROOT / "results" / f"{name}.pid"
        if pid_p.exists():
            pid = pid_p.read_text().strip()
            if Path(f"/proc/{pid}").exists():
                print("ALREADY_RUNNING", name, pid, flush=True)
                return

    # Prefer FULL resume (predictions.jsonl append). Smoke already done offline.
    log = ROOT / "results" / "socrates_full.log"
    cmd = (
        "nohup env SOCRATES_MODEL=socratesft/socrates-qwen2.5-14b-sft "
        "SMOKE_STUDIES=0 MAX_PER_CELL=0 "
        f"python3 -u {runner} > {log} 2>&1 & echo $! > {ROOT}/results/socrates_full.pid"
    )
    subprocess.run(["bash", "-lc", cmd], check=True)
    time.sleep(2)
    print("STARTED", (ROOT / "results" / "socrates_full.pid").read_text().strip(), flush=True)


if __name__ == "__main__":
    main()
