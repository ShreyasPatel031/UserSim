#!/usr/bin/env python3
"""Boot Qwen3-8B-Base Socrates floor Wasserstein on Colab. Idempotent + resume."""
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

    print(
        "GPU",
        torch.cuda.get_device_name(0),
        round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1),
        flush=True,
    )
    for d in [
        ROOT / "scripts",
        ROOT / "data" / "SocSci210_meta" / "metadata",
        ROOT / "results" / "qwen3_8b_floor_socrates",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    runner = ROOT / "scripts" / "colab_qwen3_8b_floor_socrates_vllm.py"
    if not runner.exists():
        raise SystemExit("missing colab_qwen3_8b_floor_socrates_vllm.py")

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

    for name in ("floor_socrates_full",):
        pid_p = ROOT / "results" / f"{name}.pid"
        if pid_p.exists():
            pid = pid_p.read_text().strip()
            if Path(f"/proc/{pid}").exists():
                print("ALREADY_RUNNING", name, pid, flush=True)
                return

    summary = ROOT / "results" / "qwen3_8b_floor_socrates" / "SUMMARY.json"
    if summary.exists() and summary.stat().st_size > 50:
        print("ALREADY_DONE", summary, flush=True)
        return

    log = ROOT / "results" / "floor_socrates_full.log"
    # Prefer smaller batches on T4
    cmd = (
        "nohup env SMOKE_STUDIES=0 FLOOR_MODEL=Qwen/Qwen3-8B-Base "
        "MAX_NUM_SEQS=64 CHUNK=256 GPU_MEM_UTIL=0.88 "
        f"python3 -u {runner} > {log} 2>&1 & echo $! > {ROOT}/results/floor_socrates_full.pid"
    )
    subprocess.run(["bash", "-lc", cmd], check=True)
    time.sleep(2)
    print("STARTED", (ROOT / "results" / "floor_socrates_full.pid").read_text().strip(), flush=True)


if __name__ == "__main__":
    main()
