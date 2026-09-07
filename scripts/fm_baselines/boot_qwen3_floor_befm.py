#!/usr/bin/env python3
"""Boot remaining Qwen3-8B-Base BehaviorBench floor on Colab.

Protocol: smoke → vLLM concurrency ≥ 32 → watchdog armed. Resume completed tasks.
Conservative: one GPU, L4 only, skip install if present, do not redo finished tasks.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/content/fm_baselines")
RESULTS = ROOT / "results" / "qwen3_8b_base_befm"


def sh(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    print("+", cmd, flush=True)
    return subprocess.run(cmd, shell=True, check=check)


def gpu_ok() -> None:
    import torch

    if not torch.cuda.is_available():
        raise SystemExit("PROTOCOL: no GPU. Refuse to burn a CPU Colab session.")
    name = torch.cuda.get_device_name(0)
    gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print("GPU", name, round(gb, 1), flush=True)
    # 8B bf16 + KV needs ~20GB. T4 16GB will OOM and waste units.
    if gb < 20:
        raise SystemExit(
            f"PROTOCOL: {name} has {gb:.1f} GB. Need L4/A100 (≥20GB). "
            "Do not start the 8B vLLM floor on T4."
        )


def main() -> None:
    gpu_ok()
    for d in (ROOT / "scripts", ROOT / "data" / "BehaviorBench", RESULTS):
        d.mkdir(parents=True, exist_ok=True)

    sh("apt-get install -y -qq ninja-build", check=False)
    sh(f"{sys.executable} -m pip install -q ninja", check=False)

    marker = ROOT / "WATCHDOG_ARMED"
    marker.write_text("colab-supervisor\n")
    os.environ["WATCHDOG_ARMED"] = "1"
    os.environ["WATCHDOG_MARKER"] = str(marker)
    os.environ.setdefault("ROOT", str(ROOT))
    os.environ.setdefault("CONCURRENCY", "32")
    os.environ.setdefault("MAX_NUM_SEQS", "64")
    os.environ.setdefault("FLOOR_MODEL", "Qwen/Qwen3-8B-Base")

    runner = ROOT / "scripts" / "colab_qwen3_8b_floor_befm.py"
    if not runner.exists():
        raise SystemExit("missing colab_qwen3_8b_floor_befm.py")
    proto = ROOT / "scripts" / "protocol.py"
    if not proto.exists():
        raise SystemExit("missing protocol.py")
    if not (ROOT / "data" / "BehaviorBench" / "behaviorbench_indices.json").exists():
        raise SystemExit("missing BehaviorBench data")

    pid_p = ROOT / "results" / "floor_befm_full.pid"
    if pid_p.exists():
        pid = pid_p.read_text().strip()
        if Path(f"/proc/{pid}").exists():
            print("ALREADY_RUNNING", pid, flush=True)
            return

    summary = RESULTS / "SUMMARY.json"
    if summary.exists():
        try:
            import json

            d = json.loads(summary.read_text())
            if d.get("complete"):
                print("ALREADY_DONE", summary, flush=True)
                return
        except Exception:
            pass

    log = ROOT / "results" / "floor_befm_full.log"
    wrapper = ROOT / "scripts" / "run_qwen_befm_colab.sh"
    if not wrapper.exists():
        raise SystemExit("missing run_qwen_befm_colab.sh")
    os.chmod(wrapper, 0o755)
    subprocess.run(
        [
            "bash",
            "-lc",
            f"nohup bash {wrapper} >> {log} 2>&1 & echo $! > {pid_p}",
        ],
        check=True,
    )
    time.sleep(2)
    print("STARTED", pid_p.read_text().strip(), "smoke_present", (RESULTS / "SMOKE_OK.json").exists(), flush=True)


if __name__ == "__main__":
    main()
