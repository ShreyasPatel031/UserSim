#!/usr/bin/env python3
"""Create/start GCP Spot T4 VMs for the Qwen Psych-101 NLL floor (batched).

Default: 2 shards (2x T4) so wall time is hours, not days.
Labels usersim-spot-watch=true. Uses injected GCP secrets.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gcp_auth import (  # noqa: E402
    activate_service_account,
    gcloud_bin,
    gcloud_env,
    project_id,
    watchdog_zone,
)
from protocol import require_injected_gcp  # noqa: E402

HERE = Path(__file__).resolve().parent
FILES = [
    "colab_qwen3_8b_floor_psych101_nll.py",
    "protocol.py",
    "gcp_auth.py",
    "run_qwen_psych101_full.sh",
    "usersim-floor-psych101.service",
    "install_psych101_floor.sh",
]
NUM_SHARDS = int(os.environ.get("PSYCH101_NUM_SHARDS", "2"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "4"))
MACHINE = os.environ.get("PSYCH101_MACHINE", "n1-standard-8")
ACCEL = os.environ.get("PSYCH101_ACCEL", "nvidia-tesla-t4")


def sh(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd)[:240], flush=True)
    return subprocess.run(cmd, check=check, env=gcloud_env(), text=True, capture_output=True)


def vm_name(shard: int) -> str:
    return "fm-floor-psych101" if NUM_SHARDS == 1 else f"fm-floor-psych101-s{shard}"


def ensure_vm(g: str, p: str, z: str, name: str) -> None:
    desc = sh(
        [g, "compute", "instances", "describe", name, f"--zone={z}", f"--project={p}"],
        check=False,
    )
    if desc.returncode == 0:
        status = ""
        for line in (desc.stdout or "").splitlines():
            if line.strip().startswith("status:"):
                status = line.split(":", 1)[1].strip()
        print(f"{name} exists status={status}", flush=True)
        if status == "TERMINATED":
            sh([g, "compute", "instances", "start", name, f"--zone={z}", f"--project={p}"])
            time.sleep(15)
        return

    startup_path = HERE / ".psych101_startup.sh"
    startup_path.write_text(
        """#!/bin/bash
set -eux
exec > /var/log/fm-psych101-startup.log 2>&1
apt-get update
apt-get install -y python3-pip python3-venv git curl
curl -fsSL https://raw.githubusercontent.com/GoogleCloudPlatform/compute-gpu-installation/main/linux/install_gpu_driver.py -o /tmp/install_gpu_driver.py
python3 /tmp/install_gpu_driver.py || true
nvidia-smi || true
mkdir -p /opt/usersim_fm/scripts /opt/usersim_fm/data /opt/usersim_fm/results /opt/usersim_fm/logs /opt/usersim_fm/hf_home
touch /opt/usersim_fm/READY
"""
    )
    cmd = [
        g,
        "compute",
        "instances",
        "create",
        name,
        f"--project={p}",
        f"--zone={z}",
        f"--machine-type={MACHINE}",
        f"--accelerator=type={ACCEL},count=1",
        "--maintenance-policy=TERMINATE",
        "--provisioning-model=SPOT",
        "--instance-termination-action=STOP",
        "--boot-disk-size=200GB",
        "--image-family=ubuntu-2204-lts",
        "--image-project=ubuntu-os-cloud",
        "--scopes=cloud-platform",
        "--labels=usersim-fleet=floor,usersim-spot-watch=true",
        f"--metadata-from-file=startup-script={startup_path}",
    ]
    try:
        r = sh(cmd, check=False)
        print(((r.stdout or "") + (r.stderr or ""))[-1500:], flush=True)
        if r.returncode != 0:
            raise SystemExit(f"create {name} failed")
    finally:
        startup_path.unlink(missing_ok=True)


def wait_ready(g: str, p: str, z: str, name: str) -> None:
    for attempt in range(40):
        r = sh(
            [
                g,
                "compute",
                "ssh",
                name,
                f"--zone={z}",
                f"--project={p}",
                "--tunnel-through-iap",
                "--command=test -f /opt/usersim_fm/READY && nvidia-smi -L",
            ],
            check=False,
        )
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0 and "UUID" in out:
            print(f"{name} READY", out[-200:], flush=True)
            return
        print(f"{name} waiting ready ({attempt}) {out[-200:]}", flush=True)
        time.sleep(20)
    raise SystemExit(f"{name} not ready")


def deploy_shard(g: str, p: str, z: str, shard: int) -> None:
    name = vm_name(shard)
    ensure_vm(g, p, z, name)
    wait_ready(g, p, z, name)
    remote = "/tmp/usersim_psych101_scripts"
    sh(
        [
            g,
            "compute",
            "ssh",
            name,
            f"--zone={z}",
            f"--project={p}",
            "--tunnel-through-iap",
            f"--command=sudo mkdir -p {remote} && sudo chmod 777 {remote}",
        ]
    )
    for fname in FILES:
        sh(
            [
                g,
                "compute",
                "scp",
                str(HERE / fname),
                f"{name}:{remote}/{fname}",
                f"--zone={z}",
                f"--project={p}",
                "--tunnel-through-iap",
            ]
        )
    hf = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or ""
    if hf:
        tok_path = HERE / ".hf_token_tmp"
        tok_path.write_text(hf)
        try:
            sh(
                [
                    g,
                    "compute",
                    "scp",
                    str(tok_path),
                    f"{name}:{remote}/hf_token",
                    f"--zone={z}",
                    f"--project={p}",
                    "--tunnel-through-iap",
                ]
            )
        finally:
            tok_path.unlink(missing_ok=True)

    install_cmd = (
        f"sudo SHARD_ID={shard} NUM_SHARDS={NUM_SHARDS} BATCH_SIZE={BATCH_SIZE} "
        f"bash {remote}/install_psych101_floor.sh"
    )
    r = sh(
        [
            g,
            "compute",
            "ssh",
            name,
            f"--zone={z}",
            f"--project={p}",
            "--tunnel-through-iap",
            f"--command={install_cmd}",
        ],
        check=False,
    )
    print(((r.stdout or "") + (r.stderr or ""))[-2000:], flush=True)
    if r.returncode != 0:
        raise SystemExit(f"install failed on {name}")


def main() -> None:
    require_injected_gcp()
    activate_service_account()
    g = gcloud_bin()
    p = project_id()
    z = watchdog_zone()  # same zone as minitaur T4s
    print(f"deploying {NUM_SHARDS} shard(s) in {z} batch={BATCH_SIZE}", flush=True)
    for shard in range(NUM_SHARDS):
        deploy_shard(g, p, z, shard)
    print("PSYCH101_GCP_DEPLOYED", NUM_SHARDS, flush=True)


if __name__ == "__main__":
    main()
