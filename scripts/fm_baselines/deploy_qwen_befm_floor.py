#!/usr/bin/env python3
"""Upload floor scripts and restart the VM job. Uses injected secrets."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gcp_auth import activate_service_account, gcloud_bin, gcloud_env, project_id, zone
from protocol import require_injected_gcp

HERE = Path(__file__).resolve().parent
FILES = [
    "colab_qwen3_8b_floor_befm.py",
    "protocol.py",
    "run_qwen_befm_full.sh",
    "usersim-floor-befm.service",
    "gcp_auth.py",
    "preflight_gpu_eval.py",
    "watch_qwen_befm_floor.sh",
]


def sh(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env=gcloud_env())


def main() -> None:
    require_injected_gcp()
    activate_service_account()
    vm = "fm-floor-qwen-l4"
    z = zone()
    p = project_id()
    g = gcloud_bin()
    remote = "/tmp/usersim_floor_scripts"
    sh(
        [
            g,
            "compute",
            "ssh",
            vm,
            f"--zone={z}",
            f"--project={p}",
            "--tunnel-through-iap",
            "--command=mkdir -p /tmp/usersim_floor_scripts",
        ]
    )
    for name in FILES:
        sh(
            [
                g,
                "compute",
                "scp",
                str(HERE / name),
                f"{vm}:{remote}/{name}",
                f"--zone={z}",
                f"--project={p}",
                "--tunnel-through-iap",
            ]
        )
    install = (
        "sudo systemctl stop usersim-floor-befm.service || true; "
        "sudo pkill -f vllm.entrypoints || true; "
        "sudo pkill -f colab_qwen3_8b_floor_befm.py || true; "
        f"sudo mkdir -p /opt/usersim_fm/scripts /opt/usersim_fm && "
        f"sudo cp {remote}/*.py {remote}/*.sh {remote}/*.service /opt/usersim_fm/scripts/ && "
        "sudo cp /opt/usersim_fm/scripts/usersim-floor-befm.service /etc/systemd/system/ && "
        "sudo chmod +x /opt/usersim_fm/scripts/*.sh && "
        "sudo touch /opt/usersim_fm/WATCHDOG_ARMED && sudo chmod 666 /opt/usersim_fm/WATCHDOG_ARMED && "
        "sudo systemctl daemon-reload && "
        "sudo systemctl enable usersim-floor-befm.service && "
        "sudo systemctl restart usersim-floor-befm.service && "
        "echo DEPLOY_OK && sudo systemctl is-active usersim-floor-befm.service"
    )
    sh(
        [
            g,
            "compute",
            "ssh",
            vm,
            f"--zone={z}",
            f"--project={p}",
            "--tunnel-through-iap",
            f"--command={install}",
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
