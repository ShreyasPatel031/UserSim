#!/usr/bin/env python3
"""One Colab T4 for the Qwen3-8B-Base Psych-101 NLL floor.

This Colab account only entitles T4 (L4/A100 rejected). 8B vLLM bf16 cannot
fit, so NLL uses 4-bit with the char-offset mask. Smoke first, then full.
Supervisor is the watchdog. Do not start a second Colab GPU.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gcp_auth import activate_service_account, ensure_adc  # noqa: E402
from protocol import require_injected_gcp  # noqa: E402

HERE = Path(__file__).resolve().parent
SESSION = "fm-floor-psych101"
AUTH = ["colab", "--auth=adc"]
REMOTE = "/content/fm_baselines"


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


def main() -> None:
    require_injected_gcp()
    ensure_adc()
    activate_service_account()

    st = colab("status", "-s", SESSION)
    blob = ((st.stdout or "") + (st.stderr or "")).lower()
    if st.returncode != 0 or "not found" in blob:
        print(must(colab("new", "-s", SESSION, "--gpu", "T4", timeout=300), "new T4")[-400:])
    else:
        print("reusing", SESSION, flush=True)

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
                f"Path('{REMOTE}/WATCHDOG_ARMED').write_text('1\\n')\n"
                f"print('ok')\n"
            ),
        ),
        "mkdir",
    )
    for name in ("boot_qwen3_floor_psych101.py", "colab_qwen3_8b_floor_psych101_nll.py"):
        must(colab("upload", "-s", SESSION, str(HERE / name), f"{REMOTE}/scripts/{name}"), f"upload {name}")

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

    print(
        must(
            colab(
                "exec",
                "-s",
                SESSION,
                "--timeout",
                "600",
                input_text=f"import subprocess,sys\nsubprocess.check_call([sys.executable,'-u','{REMOTE}/scripts/boot_qwen3_floor_psych101.py'])\n",
            ),
            "boot",
        )[-1500:]
    )
    print("COLAB_PSYCH101_BOOTED", SESSION, flush=True)


if __name__ == "__main__":
    sys.exit(main())
