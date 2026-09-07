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
    sh(
        [
            g,
            "compute",
            "scp",
            str(HERE / "install_floor.sh"),
            f"{vm}:{remote}/install_floor.sh",
            f"--zone={z}",
            f"--project={p}",
            "--tunnel-through-iap",
        ]
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
            "--command=bash /tmp/usersim_floor_scripts/install_floor.sh",
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
