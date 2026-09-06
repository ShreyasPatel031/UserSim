#!/usr/bin/env python3
"""Patch BehaviorBench BLEURT scoring to run in an isolated CPU subprocess.

Why: on T4 Spot VMs, importing TensorFlow in the same process that already
loaded torch/triton (or after SIGKILL'd vLLM) segfaults in libtriton.so.
A fresh interpreter with CUDA_VISIBLE_DEVICES= avoids that.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

NEW_HELPERS = r'''
_bleurt_gpu_freed = False


def _befm_free_gpu_before_bleurt() -> None:
    """vLLM + TF/BLEURT segfault on shared T4; kill GPU holders before scoring."""
    global _bleurt_gpu_freed
    import os
    import subprocess
    import time

    if os.environ.get("BEFM_KEEP_VLLM_FOR_BLEURT", "").strip() in {"1", "true", "TRUE"}:
        return
    if _bleurt_gpu_freed:
        return
    print("BEFM: freeing GPU before BLEURT/TF metrics...", flush=True)
    for pat in (
        "vllm serve",
        "VLLM::EngineCore",
        "vllm.entrypoints",
        "vllm.worker",
        "multiproc_worker",
    ):
        subprocess.run(["pkill", "-9", "-f", pat], check=False, capture_output=True)
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
            text=True,
        )
        for line in out.splitlines():
            pid = (line.strip().split(",")[0] if line.strip() else "").strip()
            if pid.isdigit():
                subprocess.run(["kill", "-9", pid], check=False, capture_output=True)
    except Exception as e:  # noqa: BLE001
        print(f"BEFM: nvidia-smi kill skipped: {e}", flush=True)
    time.sleep(5)
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["NVIDIA_VISIBLE_DEVICES"] = "void"
    _bleurt_gpu_freed = True
    print("BEFM: GPU free attempt done", flush=True)


def _bleurt_score_subprocess(predictions: list[str], references: list[str]) -> float:
    """Score in a fresh interpreter so TF never shares an address space with torch/triton."""
    import json
    import os
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    ckpt = os.environ.get(
        "BEHAVIORBENCH_BLEURT_PATH",
        os.environ.get("BEFM_BLEURT_PATH", "/opt/usersim_fm/models/BLEURT-20"),
    )
    worker = r"""
import json, os, sys
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["NVIDIA_VISIBLE_DEVICES"] = "void"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
inp, outp, ckpt = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(inp))
preds, refs = data["predictions"], data["references"]
import tensorflow as tf
try:
    tf.config.set_visible_devices([], "GPU")
except Exception:
    pass
from bleurt import score as bleurt_scorer
scorer = bleurt_scorer.BleurtScorer(ckpt)
scores = scorer.score(references=refs, candidates=preds)
json.dump({"score": float(sum(scores) / max(len(scores), 1)), "n": len(scores)}, open(outp, "w"))
print("BLEURT_SUBPROCESS_OK", len(scores), flush=True)
"""
    with tempfile.TemporaryDirectory(prefix="befm_bleurt_") as td:
        td_path = Path(td)
        inp = td_path / "in.json"
        outp = td_path / "out.json"
        inp.write_text(
            json.dumps({"predictions": list(predictions), "references": list(references)})
        )
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = ""
        env["NVIDIA_VISIBLE_DEVICES"] = "void"
        env["TF_CPP_MIN_LOG_LEVEL"] = "3"
        print(f"BEFM: BLEURT subprocess n={len(predictions)} ckpt={ckpt}", flush=True)
        r = subprocess.run(
            [sys.executable, "-c", worker, str(inp), str(outp), ckpt],
            env=env,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("BEFM_BLEURT_TIMEOUT_SEC", "3600")),
        )
        if r.returncode != 0:
            raise RuntimeError(
                "BLEURT subprocess failed rc=%s\nSTDOUT:\n%s\nSTDERR:\n%s"
                % (r.returncode, r.stdout[-4000:], r.stderr[-4000:])
            )
        if outp.exists():
            return float(json.loads(outp.read_text())["score"])
        raise RuntimeError("BLEURT subprocess produced no output: " + r.stdout[-2000:])


def bleurt_score(predictions: list[str], references: list[str]) -> float:
    """BLEURT via isolated subprocess (avoids TF+torch/triton segfault on T4)."""
    _befm_free_gpu_before_bleurt()
    if not predictions:
        return 0.0
    return _bleurt_score_subprocess(predictions, references)

'''


def patch_file(path: Path) -> bool:
    text = path.read_text()
    markers = [
        "\n_bleurt_gpu_freed",
        "\ndef _befm_free_gpu_before_bleurt",
        "\ndef _befm_release_gpu_before_bleurt",
        "\n# Cache for BLEURT",
        "\n_bleurt_cache",
        "\ndef bleurt_score",
    ]
    starts = [text.find(m) for m in markers if text.find(m) != -1]
    if not starts:
        print(f"SKIP {path}: no bleurt_score/helpers found")
        return False
    start = min(starts)

    # If we start at helpers before bleurt_score, cut through end of bleurt_score.
    bleurt_def = text.find("\ndef bleurt_score", start)
    if bleurt_def == -1:
        bleurt_def = text.find("\ndef bleurt_score")
    if bleurt_def == -1:
        print(f"SKIP {path}: bleurt_score missing")
        return False
    rest = text[bleurt_def + 1 :]
    m = re.search(r"\ndef [a-zA-Z_]", rest)
    if not m:
        print(f"SKIP {path}: cannot find end of bleurt_score")
        return False
    end = bleurt_def + 1 + m.start()
    new_text = text[:start] + "\n" + NEW_HELPERS + "\n" + text[end:]
    # Register alias if METRIC_REGISTRY uses bleurt_score name already present later — leave as is.
    bak = path.with_suffix(path.suffix + ".bak_bleurt_subproc")
    if not bak.exists():
        bak.write_text(text)
    path.write_text(new_text)
    print(f"PATCHED {path}")
    return True


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        paths = [
            Path("/opt/usersim_fm/behaviorbench_eval/src/behaviorbench/eval/metrics.py"),
            Path("/content/fm_baselines/behaviorbench_eval/src/behaviorbench/eval/metrics.py"),
        ]
    n = 0
    for p in paths:
        if p.exists():
            n += int(patch_file(p))
        else:
            print(f"missing {p}")
    return 0 if n else 1


if __name__ == "__main__":
    raise SystemExit(main())
