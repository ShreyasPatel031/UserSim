#!/usr/bin/env python3
"""Boot Qwen3-8B-Base Psych-101 floor NLL on Colab. Idempotent + resume."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/content/fm_baselines")


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def write_hf_token() -> None:
    import os

    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or ""
    if not tok:
        cached = Path.home() / ".cache" / "huggingface" / "token"
        if cached.exists():
            tok = cached.read_text().strip()
    if not tok:
        return
    os.environ["HF_TOKEN"] = tok
    os.environ["HUGGING_FACE_HUB_TOKEN"] = tok
    p = Path.home() / ".cache" / "huggingface"
    p.mkdir(parents=True, exist_ok=True)
    (p / "token").write_text(tok)


def main() -> None:
    import torch

    write_hf_token()

    print(
        "GPU",
        torch.cuda.get_device_name(0),
        round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1),
        flush=True,
    )
    for d in [ROOT / "scripts", ROOT / "data", ROOT / "results" / "qwen3_8b_floor_psych101"]:
        d.mkdir(parents=True, exist_ok=True)

    runner = ROOT / "scripts" / "colab_qwen3_8b_floor_psych101_nll.py"
    if not runner.exists():
        raise SystemExit("missing colab_qwen3_8b_floor_psych101_nll.py")

    data = ROOT / "data" / "Psych-101-test" / "prompts_testing_t1.jsonl"
    if not data.exists():
        sh(f"{sys.executable} -m pip install -q -U 'huggingface_hub>=1.5.0'")
        sh(
            "hf buckets sync hf://buckets/shreyaspatel/Psych-101-test-bucket "
            "/content/fm_baselines/data/Psych-101-test"
        )
    print("rows", sum(1 for _ in open(data)), flush=True)

    marker = ROOT / "WATCHDOG_ARMED"
    marker.write_text("colab-supervisor\n")

    for name in ("floor_psych101_full",):
        pid_p = ROOT / "results" / f"{name}.pid"
        if pid_p.exists():
            pid = pid_p.read_text().strip()
            if Path(f"/proc/{pid}").exists():
                print("ALREADY_RUNNING", name, pid, flush=True)
                return

    summary = ROOT / "results" / "qwen3_8b_floor_psych101" / "SUMMARY.json"
    if summary.exists() and summary.stat().st_size > 50:
        try:
            import json

            d = json.loads(summary.read_text())
            if (d.get("coverage") or {}).get("complete"):
                print("ALREADY_DONE", summary, flush=True)
                return
        except Exception:
            pass

    log = ROOT / "results" / "floor_psych101_full.log"
    smoke = ROOT / "results" / "qwen3_8b_floor_psych101" / "SMOKE_OK.json"
    env_file = ROOT / "results" / ".psych_env"
    extra_env = ""
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                extra_env += f" {k}={v}"
    # Defaults: BATCH_SIZE auto from GPU mem inside runner unless overridden.
    cmd = (
        "export WATCHDOG_ARMED=1 WATCHDOG_MARKER=/content/fm_baselines/WATCHDOG_ARMED "
        f"MAX_SEQ=4096 FLOOR_MODEL=Qwen/Qwen3-8B-Base{extra_env}; "
        "if [ -f ~/.cache/huggingface/token ]; then "
        "export HF_TOKEN=$(cat ~/.cache/huggingface/token); "
        "export HUGGING_FACE_HUB_TOKEN=$HF_TOKEN; fi; "
        f"if [ ! -f {smoke} ]; then echo PROTOCOL: smoke first; "
        f"MODE=smoke python3 -u {runner} >> {log} 2>&1; fi; "
        f"MODE=full python3 -u {runner} >> {log} 2>&1"
    )
    subprocess.run(
        ["bash", "-lc", f"nohup bash -lc {cmd!r} > {log}.boot 2>&1 & echo $! > {ROOT}/results/floor_psych101_full.pid"],
        check=True,
    )
    time.sleep(2)
    print("STARTED", (ROOT / "results" / "floor_psych101_full.pid").read_text().strip(), flush=True)


if __name__ == "__main__":
    main()
