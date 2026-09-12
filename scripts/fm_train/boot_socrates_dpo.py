#!/usr/bin/env python3
"""Stamped driver for Socrates QLoRA DPO from checkpoint-425.

Stages (idempotent across Spot preemption):

  1 install_train_deps   ensure TRL in the train venv
  2 pairs_smoke          tiny contrastive pair set
  3 format_smoke         SYSTEM/chat parity + pair sanity (BLOCKS on fail)
  4 train_smoke          20 DPO steps from ckpt-425
  5 pairs_full           full demographic-contrastive pairs from SFT corpus
  6 train_full           1 epoch DPO
  7 eval_full            full-40 Acc+W (optional; set RUN_EVAL=1)

Kill rules after eval (recorded in DECISION.json): Acc must clearly beat ~0.61
and W must stay ≤ 0.16 vs ckpt-425's 0.1418 / 60.6% Acc.
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
RESULTS = ROOT / "results" / "socrates_dpo"
STAMPS = RESULTS / "stamps"
SFT_CORPUS = ROOT / "data" / "socrates_sft.jsonl"
PAIRS_SMOKE = ROOT / "data" / "socrates_dpo_pairs_smoke.jsonl"
PAIRS_FULL = ROOT / "data" / "socrates_dpo_pairs.jsonl"
ADAPTER_SMOKE = ROOT / "adapters" / "socrates_dpo_smoke"
ADAPTER_FULL = ROOT / "adapters" / "socrates_qwen3_8b_dpo"
# Prefer exact checkpoint-425; also accept the eval alias ckpt425.
_DEFAULT_ADAPTER = ROOT / "adapters" / "socrates_qwen3_8b_qlora" / "checkpoint-425"
if not _DEFAULT_ADAPTER.exists() and (ROOT / "adapters" / "ckpt425").exists():
    _DEFAULT_ADAPTER = ROOT / "adapters" / "ckpt425"
SFT_ADAPTER = Path(os.environ.get("SFT_ADAPTER", str(_DEFAULT_ADAPTER)))
MODEL = os.environ.get("SFT_MODEL", "Qwen/Qwen3-8B-Base")
STOP_AFTER = os.environ.get("STOP_AFTER", "").strip()
RUN_EVAL = os.environ.get("RUN_EVAL", "1") == "1"
TRAIN_VENV = ROOT / "venvs" / "train"
TRAIN_PY = os.environ.get("TRAIN_PY", str(TRAIN_VENV / "bin" / "python3"))
# Eval runner lives next to scripts/ on this VM (not under fm_baselines/).
EVAL_RUNNER = Path(
    os.environ.get(
        "EVAL_RUNNER",
        str(SCRIPTS / "colab_qwen3_8b_floor_socrates_vllm.py"),
    )
)


def log(msg: str) -> None:
    print(f"[dpo-boot {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd: str, env: dict | None = None, timeout: int | None = None) -> None:
    log("+ " + cmd)
    full = dict(os.environ)
    full["PYTHONPATH"] = f"{FM_TRAIN}:{full.get('PYTHONPATH', '')}"
    full["ROOT"] = str(ROOT)
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
    if stamped(name):
        log(f"skip {name} (stamped)")
        return False
    return True


def stop_here(name: str) -> bool:
    return STOP_AFTER == name


def require_ckpt425() -> None:
    if not SFT_ADAPTER.exists():
        raise SystemExit(f"SFT adapter missing: {SFT_ADAPTER}")
    if "1175" in str(SFT_ADAPTER) or "1550" in str(SFT_ADAPTER) or "1525" in str(SFT_ADAPTER):
        raise SystemExit(f"refusing DPO from non-425 ckpt: {SFT_ADAPTER}")
    log(f"SFT adapter OK: {SFT_ADAPTER}")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    require_ckpt425()
    if not Path(TRAIN_PY).exists():
        raise SystemExit(
            f"train venv missing at {TRAIN_PY}; run boot_socrates_sft.py install_train_venv first"
        )

    if stage("install_train_deps"):
        sh(f"{TRAIN_PY} -m pip install -q -U pip wheel")
        sh(
            f"{TRAIN_PY} -m pip install -q "
            "'transformers>=4.44,<5' 'peft>=0.12' 'trl>=0.9' "
            "datasets accelerate bitsandbytes sentencepiece protobuf"
        )
        sh(f"{TRAIN_PY} -c \"import trl, peft, transformers; print('trl', trl.__version__)\"")
        stamp("install_train_deps")
    if stop_here("install_train_deps"):
        return

    if not SFT_CORPUS.exists():
        raise SystemExit(f"SFT corpus missing: {SFT_CORPUS}")

    if stage("pairs_smoke"):
        sh(
            f"{TRAIN_PY} -u {FM_TRAIN}/build_socrates_dpo_pairs.py "
            f"--sft-corpus {SFT_CORPUS} --out {PAIRS_SMOKE} "
            f"--limit-rows 4000 --max-pairs 256"
        )
        stamp("pairs_smoke")
    if stop_here("pairs_smoke"):
        return

    if stage("format_smoke"):
        sh(
            f"{TRAIN_PY} -u {FM_TRAIN}/smoke_socrates_dpo.py",
            env={
                "DPO_CORPUS": str(PAIRS_SMOKE),
                "SFT_MODEL": MODEL,
                "EVAL_RUNNER": str(EVAL_RUNNER),
                "ROOT": str(ROOT),
            },
        )
        stamp("format_smoke")
    if stop_here("format_smoke"):
        return

    if stage("train_smoke"):
        sh(
            f"{TRAIN_PY} -u {FM_TRAIN}/dpo_socrates_qlora.py "
            f"--data {PAIRS_SMOKE} --out {ADAPTER_SMOKE} "
            f"--sft-adapter {SFT_ADAPTER} --max-steps 20 --save-steps 20 "
            f"--micro-batch 1 --grad-accum 8 --limit-rows 128",
            env={
                "RESUME": "0",
                "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
            },
        )
        stamp("train_smoke")
    if stop_here("train_smoke"):
        return

    if stage("pairs_full"):
        sh(
            f"{TRAIN_PY} -u {FM_TRAIN}/build_socrates_dpo_pairs.py "
            f"--sft-corpus {SFT_CORPUS} --out {PAIRS_FULL}"
        )
        stamp("pairs_full")
    if stop_here("pairs_full"):
        return

    if stage("train_full"):
        sh(
            f"{TRAIN_PY} -u {FM_TRAIN}/dpo_socrates_qlora.py "
            f"--data {PAIRS_FULL} --out {ADAPTER_FULL} "
            f"--sft-adapter {SFT_ADAPTER}",
            env={
                "RESUME": "1",
                "LR": os.environ.get("LR", "1e-6"),
                "MICRO_BATCH": os.environ.get("MICRO_BATCH", "1"),
                "GRAD_ACCUM": os.environ.get("GRAD_ACCUM", "64"),
                "SAVE_STEPS": os.environ.get("SAVE_STEPS", "25"),
                "EPOCHS": os.environ.get("EPOCHS", "1"),
                "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
            },
        )
        stamp("train_full")
    if stop_here("train_full"):
        return

    if RUN_EVAL and stage("eval_full"):
        eval_dir = RESULTS / "eval_full"
        eval_dir.mkdir(parents=True, exist_ok=True)
        dest = ROOT / "adapters" / "ckpt425_dpo"
        sh(f"rm -rf {dest} && cp -a {ADAPTER_FULL} {dest}")
        sh(
            f"{sys.executable} -u {EVAL_RUNNER}",
            env={
                "RESULTS_DIR": str(eval_dir),
                "LORA_PATH": str(dest),
                "FLOOR_MODEL": MODEL,
                "MAX_LORA_RANK": "16",
                "SMOKE_STUDIES": "0",
                "GATE": "1",
                "SKIP_INSTALL": "1",
                "MAX_NUM_SEQS": "64",
                "CHUNK": "256",
                "GPU_MEM_UTIL": "0.88",
            },
        )
        stamp("eval_full")

    # Kill rules vs ckpt-425 champion: Acc must clearly beat ~0.61 and W ≤ 0.16.
    summary_path = RESULTS / "eval_full" / "SUMMARY.json"
    if summary_path.exists() and stage("decision"):
        summ = json.loads(summary_path.read_text())
        w = summ.get("wasserstein_mean")
        parse = summ.get("parse") or {}
        acc = summ.get("accuracy")
        if acc is None:
            acc = parse.get("accuracy") or summ.get("individual_accuracy")
        baseline_w, baseline_acc = 0.1418, 0.606
        w_ok = w is not None and float(w) <= 0.16
        acc_ok = acc is not None and float(acc) > 0.61
        keep = bool(w_ok and acc_ok)
        decision = {
            "keep": keep,
            "kill": not keep,
            "wasserstein_mean": w,
            "accuracy": acc,
            "baseline_ckpt425": {"wasserstein_mean": baseline_w, "accuracy": baseline_acc},
            "rules": {"acc_must_clearly_beat": 0.61, "w_max": 0.16},
            "reasons": [
                *([] if w_ok else [f"W={w} > 0.16 (ckpt-425 had {baseline_w})"]),
                *(
                    []
                    if acc_ok
                    else [
                        f"Acc={acc} does not clearly beat 0.61 (ckpt-425 had {baseline_acc})"
                    ]
                ),
            ],
            "parse": parse,
            "n_studies": summ.get("n_studies"),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (RESULTS / "DECISION.json").write_text(json.dumps(decision, indent=2) + "\n")
        log(json.dumps(decision, indent=2))
        stamp("decision")
        if not keep:
            log("KILL: DPO does not beat ckpt-425 on Acc/W rules")
        else:
            log("KEEP: DPO clears Acc/W kill rules")

    log("DPO boot complete")
    (RESULTS / "BOOT_DONE.json").write_text(
        json.dumps(
            {
                "sft_adapter": str(SFT_ADAPTER),
                "dpo_adapter": str(ADAPTER_FULL),
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
