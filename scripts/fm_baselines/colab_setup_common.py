"""Common Colab setup helpers for Phase 0 baseline reproduction."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path("/content/fm_baselines")
DATA = ROOT / "data"
RESULTS = ROOT / "results"
MODELS = ROOT / "models"


def sh(cmd: str, check: True) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=check)


def ensure_dirs() -> None:
    for p in (ROOT, DATA, RESULTS, MODELS):
        p.mkdir(parents=True, exist_ok=True)


def pip_install(*pkgs: str) -> None:
    sh(f"{sys.executable} -m pip install -q {' '.join(pkgs)}")


def hf_login_from_env() -> None:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if not token:
        print("WARN: no HF_TOKEN in env; public downloads only", flush=True)
        return
    pip_install("huggingface_hub>=0.34")
    from huggingface_hub import login

    login(token=token, add_to_git_credential=False)
    print("HF login OK", flush=True)
