#!/usr/bin/env python3
"""Start ONE Colab L4 for the remaining Qwen3-8B-Base BehaviorBench floor.

Conservative vs GCP: no second GPU, no A100, no T4 (OOM), resume finished
tasks, smoke before full, supervisor is the watchdog.
Uses injected ADC (COLAB_AUTH=adc). Never ask for a paste.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gcp_auth import activate_service_account, ensure_adc  # noqa: E402
from protocol import require_injected_gcp  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SESSION = "fm-floor-befm"
AUTH = ["colab", "--auth=adc"]
REMOTE_ROOT = "/content/fm_baselines"


def sh(cmd: list[str], timeout: int = 300, input_text: str | None = None) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd)[:180], flush=True)
    return subprocess.run(
        cmd, text=True, capture_output=True, timeout=timeout, input=input_text
    )


def colab(*args: str, timeout: int = 300, input_text: str | None = None) -> subprocess.CompletedProcess:
    return sh(AUTH + list(args), timeout=timeout, input_text=input_text)


def must_ok(r: subprocess.CompletedProcess, what: str) -> str:
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode != 0:
        print(out[-2000:], flush=True)
        raise SystemExit(f"{what} failed rc={r.returncode}")
    return out


def main() -> None:
    require_injected_gcp()
    ensure_adc()
    activate_service_account()

    resume = REPO / "results/fm_baselines/qwen3_8b_base_befm/qwen3_8b_base_befm_resume.tgz"
    data = REPO / "data/fm_baselines/BehaviorBench"
    if not data.exists():
        raise SystemExit(f"missing {data}")

    # Prefer an existing healthy session. Do not stack GPUs.
    sessions = colab("sessions")
    print(sessions.stdout or sessions.stderr, flush=True)

    r = colab("status", "-s", SESSION)
    st = ((r.stdout or "") + (r.stderr or "")).lower()
    if r.returncode != 0 or "not found" in st or "no active" in st:
        print("creating L4 session (not A100, not T4)", flush=True)
        out = must_ok(
            colab("new", "-s", SESSION, "--gpu", "L4", timeout=300),
            "colab new L4",
        )
        print(out[-800:], flush=True)
        if "rejected" in out.lower() or "quota" in out.lower() or "unavailable" in out.lower():
            raise SystemExit(
                "L4 not assigned. Conservative policy: do not fall through to A100/T4. Retry later."
            )
    else:
        print("reusing", SESSION, flush=True)

    files = [
        HERE / "boot_qwen3_floor_befm.py",
        HERE / "colab_qwen3_8b_floor_befm.py",
        HERE / "protocol.py",
        HERE / "run_qwen_befm_colab.sh",
    ]
    setup = (
        f"from pathlib import Path\n"
        f"Path('{REMOTE_ROOT}/scripts').mkdir(parents=True, exist_ok=True)\n"
        f"Path('{REMOTE_ROOT}/data').mkdir(parents=True, exist_ok=True)\n"
        f"Path('{REMOTE_ROOT}/results/qwen3_8b_base_befm').mkdir(parents=True, exist_ok=True)\n"
        f"Path('{REMOTE_ROOT}/WATCHDOG_ARMED').write_text('1\\n')\n"
        f"print('dirs_ok')\n"
    )
    must_ok(colab("exec", "-s", SESSION, "--timeout", "60", input_text=setup), "mkdir")

    for p in files:
        dest = f"{REMOTE_ROOT}/scripts/{p.name}"
        must_ok(colab("upload", "-s", SESSION, str(p), dest, timeout=180), f"upload {p.name}")

    # Data is 34MB — tar then one upload.
    data_tar = Path("/tmp/behaviorbench_data.tgz")
    if not data_tar.exists():
        with tarfile.open(data_tar, "w:gz") as tf:
            tf.add(data, arcname="BehaviorBench")
    must_ok(
        colab("upload", "-s", SESSION, str(data_tar), f"{REMOTE_ROOT}/behaviorbench_data.tgz", timeout=300),
        "upload BehaviorBench",
    )
    unpack = (
        f"import tarfile\n"
        f"from pathlib import Path\n"
        f"tarfile.open('{REMOTE_ROOT}/behaviorbench_data.tgz').extractall('{REMOTE_ROOT}/data')\n"
        f"print('bb', Path('{REMOTE_ROOT}/data/BehaviorBench/behaviorbench_indices.json').exists())\n"
    )
    print(must_ok(colab("exec", "-s", SESSION, "--timeout", "120", input_text=unpack), "unpack data")[-400:])

    if resume.exists():
        must_ok(
            colab(
                "upload",
                "-s",
                SESSION,
                str(resume),
                f"{REMOTE_ROOT}/qwen3_8b_base_befm_resume.tgz",
                timeout=180,
            ),
            "upload resume",
        )
        resume_py = (
            f"import tarfile\n"
            f"from pathlib import Path\n"
            f"tarfile.open('{REMOTE_ROOT}/qwen3_8b_base_befm_resume.tgz').extractall('{REMOTE_ROOT}/results')\n"
            f"p=Path('{REMOTE_ROOT}/results/qwen3_8b_base_befm/PROGRESS.json')\n"
            f"print(p.read_text() if p.exists() else 'no-progress')\n"
        )
        print(must_ok(colab("exec", "-s", SESSION, "--timeout", "120", input_text=resume_py), "unpack resume")[-800:])

    hf = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or ""
    # Set token on the VM without printing it.
    if hf:
        token_py = (
            "import os,pathlib\n"
            f"os.environ['HF_TOKEN']={hf!r}\n"
            "os.environ['HUGGING_FACE_HUB_TOKEN']=os.environ['HF_TOKEN']\n"
            "p=pathlib.Path.home()/'.cache'/'huggingface'\n"
            "p.mkdir(parents=True, exist_ok=True)\n"
            "(p/'token').write_text(os.environ['HF_TOKEN'])\n"
            "print('hf_token_set', True)\n"
        )
        must_ok(colab("exec", "-s", SESSION, "--timeout", "60", input_text=token_py), "hf token")

    boot = (
        "import subprocess,sys\n"
        f"subprocess.check_call([sys.executable,'-u','{REMOTE_ROOT}/scripts/boot_qwen3_floor_befm.py'])\n"
    )
    print(must_ok(colab("exec", "-s", SESSION, "--timeout", "600", input_text=boot), "boot")[-1500:])
    print("COLAB_FLOOR_BOOTED", SESSION, flush=True)


if __name__ == "__main__":
    sys.exit(main())
