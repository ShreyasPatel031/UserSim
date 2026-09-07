#!/usr/bin/env python3
"""One Colab T4 for the Qwen3-8B-Base Socrates / SocSci210 Wasserstein floor.

Account entitles T4 only. 8B vLLM fp16 does not fit, so this uses vLLM 4-bit.
Smoke (32 rows, ≥1 parsed number) then full 40 unseen studies. Resume via
predictions.jsonl. Supervisor is the watchdog.

Do not start Be.FM here — that floor is on the GCP L4.
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
SESSION = "fm-floor-socrates"
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
        created = colab("new", "-s", SESSION, "--gpu", "T4", timeout=300)
        out = ((created.stdout or "") + (created.stderr or ""))
        if created.returncode != 0:
            if "TooManyAssignments" in out or "Precondition Failed" in out:
                print(
                    "QUEUED_AFTER_PSYCH101: this Colab identity only assigns one T4. "
                    "Supervisor --floor-remaining will start Socrates when Psych-101 finishes.",
                    flush=True,
                )
                return
            print(out[-2000:], flush=True)
            raise SystemExit("new T4 failed")
        print(out[-400:], flush=True)
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
    for name in ("boot_qwen3_floor_socrates.py", "colab_qwen3_8b_floor_socrates_vllm.py"):
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
                input_text=f"import subprocess,sys\nsubprocess.check_call([sys.executable,'-u','{REMOTE}/scripts/boot_qwen3_floor_socrates.py'])\n",
            ),
            "boot",
        )[-1500:]
    )
    print("COLAB_SOCRATES_BOOTED", SESSION, flush=True)


if __name__ == "__main__":
    sys.exit(main())
