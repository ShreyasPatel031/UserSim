#!/usr/bin/env python3
"""Colab L4 (preferred) for Qwen3-8B-Base Psych-101 NLL floor.

Tries L4 first for bf16 batched NLL. Falls back to T4 4-bit only if L4 is
rejected. Restores scores.jsonl / SMOKE_OK from local disk so a GPU cutover
does not wipe progress. Supervisor is the watchdog.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gcp_auth import activate_service_account, ensure_adc  # noqa: E402
from protocol import require_injected_gcp  # noqa: E402

HERE = Path(__file__).resolve().parent
SESSION = "fm-floor-psych101"
AUTH = ["colab", "--auth=adc"]
REMOTE = "/content/fm_baselines"
LOCAL_RESUME = Path(__file__).resolve().parents[2] / "results" / "fm_baselines" / "qwen3_8b_floor_psych101"
GPUS = ["L4", "T4"]  # prefer L4


def colab(*args: str, timeout: int = 300, input_text: str | None = None) -> subprocess.CompletedProcess:
    print("+", " ".join(("colab", "--auth=adc") + args)[:160], flush=True)
    return subprocess.run(
        AUTH + list(args), text=True, capture_output=True, timeout=timeout, input=input_text
    )


def must(r: subprocess.CompletedProcess, what: str) -> str:
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode != 0:
        print(out[-2000:], flush=True)
        raise SystemExit(f"{what} failed")
    return out


def ensure_session() -> str:
    st = colab("status", "-s", SESSION)
    blob = ((st.stdout or "") + (st.stderr or ""))
    low = blob.lower()
    if st.returncode == 0 and "not found" not in low:
        for g in GPUS:
            if g.lower() in low:
                print("reusing", SESSION, g, flush=True)
                return g
        print("reusing", SESSION, flush=True)
        return GPUS[0]

    last = ""
    for gpu in GPUS:
        for attempt in range(1, 8):
            r = colab("new", "-s", SESSION, "--gpu", gpu, timeout=300)
            out = ((r.stdout or "") + (r.stderr or ""))
            last = out
            print(out[-500:], flush=True)
            if r.returncode == 0:
                print("GOT", gpu, flush=True)
                return gpu
            if "TooManyAssignments" in out or "Precondition Failed" in out:
                print(f"{gpu}: quota full — stop+retry", flush=True)
                colab("stop", "-s", SESSION)
                time.sleep(15)
                continue
            if "rejected accelerator" in out.lower() or "not have quota" in out.lower():
                print(f"{gpu}: entitlement rejected — try next", flush=True)
                break
            wait = min(20 * attempt, 120)
            print(f"{gpu}: assign flaky — retry in {wait}s", flush=True)
            time.sleep(wait)
    print(last[-2000:], flush=True)
    raise SystemExit("could not assign L4 or T4")


def main() -> None:
    require_injected_gcp()
    adc = ensure_adc()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc)
    activate_service_account()

    # Free current session so we can request L4 cleanly.
    colab("stop", "-s", SESSION)
    time.sleep(5)
    gpu = ensure_session()

    must(
        colab(
            "exec",
            "-s",
            SESSION,
            "--timeout",
            "30",
            input_text=(
                f"from pathlib import Path\n"
                f"Path('{REMOTE}/scripts').mkdir(parents=True, exist_ok=True)\n"
                f"Path('{REMOTE}/results/qwen3_8b_floor_psych101').mkdir(parents=True, exist_ok=True)\n"
                f"Path('{REMOTE}/WATCHDOG_ARMED').write_text('1\\n')\n"
                f"print('ok')\n"
            ),
        ),
        "mkdir",
    )
    for name in ("boot_qwen3_floor_psych101.py", "colab_qwen3_8b_floor_psych101_nll.py"):
        must(colab("upload", "-s", SESSION, str(HERE / name), f"{REMOTE}/scripts/{name}"), f"upload {name}")

    # Restore resume artifacts from local disk
    for fname in ("scores.jsonl", "SMOKE_OK.json", "PROGRESS.json"):
        local = LOCAL_RESUME / fname
        if local.exists() and local.stat().st_size > 0:
            must(
                colab(
                    "upload",
                    "-s",
                    SESSION,
                    str(local),
                    f"{REMOTE}/results/qwen3_8b_floor_psych101/{fname}",
                ),
                f"restore {fname}",
            )

    hf = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or ""
    if hf:
        must(
            colab(
                "exec",
                "-s",
                SESSION,
                "--timeout",
                "30",
                input_text=(
                    "import os,pathlib\n"
                    f"os.environ['HF_TOKEN']={hf!r}\n"
                    "os.environ['HUGGING_FACE_HUB_TOKEN']=os.environ['HF_TOKEN']\n"
                    "p=pathlib.Path.home()/'.cache'/'huggingface'\n"
                    "p.mkdir(parents=True, exist_ok=True)\n"
                    "(p/'token').write_text(os.environ['HF_TOKEN'])\n"
                    "print('hf_ok')\n"
                ),
            ),
            "hf",
        )

    # L4: larger batches + bf16. T4: 4-bit batch 4.
    batch = "8" if gpu == "L4" else "4"
    force = "FORCE_BF16=1" if gpu == "L4" else "FORCE_4BIT=1"
    must(
        colab(
            "exec",
            "-s",
            SESSION,
            "--timeout",
            "30",
            input_text=(
                "from pathlib import Path\n"
                f"Path('/content/fm_baselines/results/.psych_env').write_text('BATCH_SIZE={batch}\\n{force}\\n')\n"
                "print('env', open('/content/fm_baselines/results/.psych_env').read())\n"
            ),
        ),
        "env",
    )

    print(
        must(
            colab(
                "exec",
                "-s",
                SESSION,
                "--timeout",
                "600",
                input_text=(
                    "import os,subprocess,sys\n"
                    "from pathlib import Path\n"
                    "envp=Path('/content/fm_baselines/results/.psych_env')\n"
                    "if envp.exists():\n"
                    "  for line in envp.read_text().splitlines():\n"
                    "    if '=' in line: k,v=line.split('=',1); os.environ[k]=v\n"
                    f"subprocess.check_call([sys.executable,'-u','{REMOTE}/scripts/boot_qwen3_floor_psych101.py'])\n"
                ),
            ),
            "boot",
        )[-1500:]
    )
    print("COLAB_PSYCH101_BOOTED", SESSION, "gpu", gpu, "batch", batch, flush=True)


if __name__ == "__main__":
    sys.exit(main())
