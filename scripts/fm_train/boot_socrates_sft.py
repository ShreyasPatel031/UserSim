#!/usr/bin/env python3
"""Staged, idempotent driver for the Socrates QLoRA SFT run.

Stages run in order and each writes a stamp, so a preempted VM re-runs only
what is missing:

  1 install        pip deps
  2 corpus_smoke   3 studies, few participants per cell
  3 format_smoke   train text == eval prompt (blocks everything on failure)
  4 train_smoke    20 optimizer steps, proves the loss moves and nothing OOMs
  5 eval_smoke     Wasserstein on 1 unseen study with the smoke adapter
  6 corpus_full    all 170 seen studies, MAX_PER_CELL participants per cell
  7 train_full     1 epoch
  8 eval_full      Wasserstein on all 40 unseen studies

Env: ROOT, MAX_PER_CELL (full corpus cap), SFT_MODEL, STOP_AFTER (stage name).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
SCRIPTS = ROOT / "scripts"
FM_TRAIN = SCRIPTS / "fm_train"
RESULTS = ROOT / "results" / "socrates_sft"
STAMPS = RESULTS / "stamps"
ADAPTER_SMOKE = ROOT / "adapters" / "socrates_smoke"
ADAPTER_FULL = ROOT / "adapters" / "socrates_qwen3_8b_qlora"
CORPUS_SMOKE = ROOT / "data" / "socrates_sft_smoke.jsonl"
CORPUS_FULL = ROOT / "data" / "socrates_sft.jsonl"
MODEL = os.environ.get("SFT_MODEL", "Qwen/Qwen3-8B-Base")
MAX_PER_CELL = os.environ.get("MAX_PER_CELL", "32")
STOP_AFTER = os.environ.get("STOP_AFTER", "").strip()
# vLLM pulls transformers 5.x, which current peft cannot import. Training gets
# its own interpreter with a transformers 4.x stack; eval keeps the vLLM one.
TRAIN_VENV = ROOT / "venvs" / "train"
TRAIN_PY = os.environ.get("TRAIN_PY", str(TRAIN_VENV / "bin" / "python3"))


def log(msg: str) -> None:
    print(f"[boot {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd: str, env: dict | None = None, timeout: int | None = None) -> None:
    log("+ " + cmd)
    full = dict(os.environ)
    full["PYTHONPATH"] = f"{FM_TRAIN}:{full.get('PYTHONPATH', '')}"
    if env:
        full.update(env)
    subprocess.run(cmd, shell=True, check=True, env=full, timeout=timeout)


def stamped(name: str) -> bool:
    return (STAMPS / name).exists()


def stamp(name: str) -> None:
    STAMPS.mkdir(parents=True, exist_ok=True)
    (STAMPS / name).write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
    log(f"stage done: {name}")


def stage(name: str) -> bool:
    """True when this stage should run now."""
    if stamped(name):
        log(f"skip {name} (stamped)")
        return False
    return True


def stop_here(name: str) -> bool:
    return STOP_AFTER == name


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    if stage("install"):
        sh(f"{py} -m pip install -q -U pip")
        # ninja: flashinfer JIT-compiles its sampling kernels at engine start.
        sh(f"{py} -m pip install -q -U datasets huggingface_hub ninja 'vllm>=0.6.0'")
        # Installing vLLM moves torch to a newer CUDA build than the image's
        # torchaudio, and the version guard then blocks every vLLM import. This
        # workload is text-only, so drop torchaudio rather than pin torch.
        sh(f"{py} -c \"from vllm import LLM\" || sudo {py} -m pip uninstall -y -q torchaudio")
        sh(f"{py} -c \"from vllm import LLM; print('vllm import ok')\"")
        stamp("install")
    if stop_here("install"):
        return

    if stage("install_train_venv"):
        if not Path(TRAIN_PY).exists():
            sh(f"{py} -m venv {TRAIN_VENV}")
        sh(f"{TRAIN_PY} -m pip install -q -U pip wheel")
        sh(
            f"{TRAIN_PY} -m pip install -q -U torch "
            "'transformers>=4.55,<5' 'peft>=0.14,<0.21' 'accelerate>=0.33' "
            "'bitsandbytes>=0.43' datasets huggingface_hub"
        )
        sh(f"{TRAIN_PY} -c \"import peft, transformers, bitsandbytes; print('train stack', transformers.__version__, peft.__version__)\"")
        stamp("install_train_venv")

    if stage("corpus_smoke"):
        sh(
            f"{py} -u {FM_TRAIN}/build_socrates_sft_corpus.py "
            f"--out {CORPUS_SMOKE} --limit-studies 3 --max-per-cell 8"
        )
        stamp("corpus_smoke")

    if stage("format_smoke"):
        sh(
            f"{TRAIN_PY} -u {FM_TRAIN}/smoke_socrates_sft.py",
            env={"SFT_CORPUS": str(CORPUS_SMOKE), "SFT_MODEL": MODEL},
        )
        stamp("format_smoke")
    if stop_here("format_smoke"):
        return

    if stage("train_smoke"):
        sh(
            f"{TRAIN_PY} -u {FM_TRAIN}/sft_socrates_qlora.py",
            env={
                "SFT_CORPUS": str(CORPUS_SMOKE),
                "SFT_OUT": str(ADAPTER_SMOKE),
                "SFT_MODEL": MODEL,
                "MAX_STEPS": "20",
                "SAVE_STEPS": "20",
                "LOG_STEPS": "2",
                "MICRO_BATCH": os.environ.get("MICRO_BATCH", "4"),
                "GRAD_ACCUM": "4",
            },
        )
        prog = json.loads((RESULTS / "PROGRESS.json").read_text())
        loss = prog.get("loss")
        if prog.get("diverged") or not isinstance(loss, (int, float)) or loss <= 0:
            raise SystemExit(f"train smoke unhealthy: {prog}")
        log(f"train smoke loss={loss}")
        stamp("train_smoke")

    if stage("eval_smoke"):
        sh(
            f"{py} -u {SCRIPTS}/colab_qwen3_8b_floor_socrates_vllm.py",
            env={
                "RESULTS_DIR": str(RESULTS / "eval_smoke"),
                "LORA_PATH": str(ADAPTER_SMOKE),
                "FLOOR_MODEL": MODEL,
                "SMOKE_STUDIES": "1",
                "MAX_NUM_SEQS": "64",
                "CHUNK": "256",
                "GPU_MEM_UTIL": "0.88",
                "SKIP_INSTALL": "1",
            },
        )
        summ = json.loads((RESULTS / "eval_smoke" / "SUMMARY.json").read_text())
        w = summ.get("wasserstein_mean")
        if w is None or not (0 < w < 1):
            raise SystemExit(f"eval smoke produced implausible W={w}")
        log(f"eval smoke W={w:.4f} (adapter is only 20 steps; sanity not quality)")
        stamp("eval_smoke")
    if stop_here("eval_smoke"):
        return

    if stage("corpus_full"):
        sh(
            f"{py} -u {FM_TRAIN}/build_socrates_sft_corpus.py "
            f"--out {CORPUS_FULL} --max-per-cell {MAX_PER_CELL}"
        )
        stamp("corpus_full")

    if stage("train_full"):
        sh(
            f"{TRAIN_PY} -u {FM_TRAIN}/sft_socrates_qlora.py",
            env={
                "SFT_CORPUS": str(CORPUS_FULL),
                "SFT_OUT": str(ADAPTER_FULL),
                "SFT_MODEL": MODEL,
                "EPOCHS": os.environ.get("EPOCHS", "1"),
                "MAX_STEPS": "-1",
            },
        )
        stamp("train_full")
    if stop_here("train_full"):
        return

    if stage("eval_full"):
        sh(
            f"{py} -u {SCRIPTS}/colab_qwen3_8b_floor_socrates_vllm.py",
            env={
                "RESULTS_DIR": str(RESULTS / "eval_full"),
                "LORA_PATH": str(ADAPTER_FULL),
                "FLOOR_MODEL": MODEL,
                "SMOKE_STUDIES": "0",
                "MAX_NUM_SEQS": "64",
                "CHUNK": "256",
                "GPU_MEM_UTIL": "0.88",
                "SKIP_INSTALL": "1",
            },
        )
        stamp("eval_full")

    summary_path = RESULTS / "eval_full" / "SUMMARY.json"
    if summary_path.exists():
        summ = json.loads(summary_path.read_text())
        gate = {
            "wasserstein_mean": summ.get("wasserstein_mean"),
            "paper_socrates_14b_sft": 0.151,
            "empirical_best": 0.125,
            "beats_paper": (summ.get("wasserstein_mean") or 9) < 0.151,
            "n_studies": summ.get("n_studies"),
            "complete": summ.get("coverage", {}).get("complete"),
        }
        (RESULTS / "GATE.json").write_text(json.dumps(gate, indent=2) + "\n")
        print(json.dumps(gate, indent=2), flush=True)
    log("ALL STAGES COMPLETE")


if __name__ == "__main__":
    main()
