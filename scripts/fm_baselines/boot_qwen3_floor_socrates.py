#!/usr/bin/env python3
"""Boot Qwen3-8B-Base Socrates floor Wasserstein on Colab. Smoke then full."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/content/fm_baselines")


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def write_hf_token() -> None:
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
    name = torch.cuda.get_device_name(0)
    mem = torch.cuda.get_device_properties(0).total_memory / 1e9
    print("GPU", name, round(mem, 1), flush=True)
    if mem < 20:
        print("T4-class GPU: using vLLM 4-bit (8B fp16 does not fit)", flush=True)

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

    marker = ROOT / "WATCHDOG_ARMED"
    marker.write_text("colab-supervisor\n")

    for proc_name in ("floor_socrates_full",):
        pid_p = ROOT / "results" / f"{proc_name}.pid"
        if pid_p.exists():
            pid = pid_p.read_text().strip()
            if Path(f"/proc/{pid}").exists():
                print("ALREADY_RUNNING", proc_name, pid, flush=True)
                return

    summary = ROOT / "results" / "qwen3_8b_floor_socrates" / "SUMMARY.json"
    if summary.exists() and summary.stat().st_size > 50:
        try:
            import json

            d = json.loads(summary.read_text())
            if d.get("complete") or (d.get("coverage") or {}).get("complete"):
                print("ALREADY_DONE", summary, flush=True)
                return
        except Exception:
            pass

    log = ROOT / "results" / "floor_socrates_full.log"
    smoke = ROOT / "results" / "qwen3_8b_floor_socrates" / "SMOKE_OK.json"
    # T4: 4-bit vLLM, max_num_seqs 64 (protocol floor). Smoke 32 rows then full.
    cmd = (
        "export WATCHDOG_ARMED=1 WATCHDOG_MARKER=/content/fm_baselines/WATCHDOG_ARMED "
        "FLOOR_MODEL=Qwen/Qwen3-8B-Base MAX_NUM_SEQS=64 CHUNK=256 GPU_MEM_UTIL=0.90 "
        "VLLM_4BIT=1 SMOKE_N=32 SOCSCI_MAPPING="
        f"{mapping}; "
        f"if [ -f {Path.home()}/.cache/huggingface/token ]; then "
        "export HF_TOKEN=$(cat ~/.cache/huggingface/token); "
        "export HUGGING_FACE_HUB_TOKEN=$HF_TOKEN; fi; "
        f"if [ ! -f {smoke} ]; then echo PROTOCOL: smoke first; "
        f"MODE=smoke python3 -u {runner} >> {log} 2>&1; fi; "
        f"MODE=full python3 -u {runner} >> {log} 2>&1"
    )
    subprocess.run(
        ["bash", "-lc", f"nohup bash -lc {cmd!r} > {log}.boot 2>&1 & echo $! > {ROOT}/results/floor_socrates_full.pid"],
        check=True,
    )
    time.sleep(2)
    print("STARTED", (ROOT / "results" / "floor_socrates_full.pid").read_text().strip(), flush=True)


if __name__ == "__main__":
    main()
