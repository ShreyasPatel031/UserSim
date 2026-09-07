#!/usr/bin/env python3
"""Arm watchdog + refuse a full GPU eval that skips protocol.

Usage (laptop/cloud agent with gcloud):
  python3 scripts/fm_baselines/preflight_gpu_eval.py --vm fm-floor-qwen-l4

Requires env PROJECT and ZONE (or --project / --zone).
Writes WATCHDOG_ARMED on the VM and prints PREFLIGHT_OK.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


def sh(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=check)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vm", required=True)
    ap.add_argument("--project", default=os.environ.get("PROJECT") or os.environ.get("CLOUDSDK_CORE_PROJECT"))
    ap.add_argument("--zone", default=os.environ.get("ZONE"))
    ap.add_argument("--watchdog-vm", default="fm-gate0-spot-watchdog")
    ap.add_argument("--watchdog-zone", default=os.environ.get("WATCHDOG_ZONE"))
    args = ap.parse_args()
    if not args.project or not args.zone:
        raise SystemExit("set --project/--zone or PROJECT and ZONE")

    g = ["gcloud", "compute"]
    sh(
        g
        + [
            "instances",
            "add-labels",
            args.vm,
            f"--zone={args.zone}",
            f"--project={args.project}",
            "--labels=usersim-spot-watch=true",
        ]
    )

    # Confirm GPU VM is up; start if needed
    desc = subprocess.check_output(
        g
        + [
            "instances",
            "describe",
            args.vm,
            f"--zone={args.zone}",
            f"--project={args.project}",
            "--format=value(status)",
        ],
        text=True,
    ).strip()
    if desc != "RUNNING":
        sh(
            g
            + [
                "instances",
                "start",
                args.vm,
                f"--zone={args.zone}",
                f"--project={args.project}",
            ]
        )

    if args.watchdog_zone:
        wstatus = subprocess.check_output(
            g
            + [
                "instances",
                "describe",
                args.watchdog_vm,
                f"--zone={args.watchdog_zone}",
                f"--project={args.project}",
                "--format=value(status)",
            ],
            text=True,
        ).strip()
        if wstatus != "RUNNING":
            sh(
                g
                + [
                    "instances",
                    "start",
                    args.watchdog_vm,
                    f"--zone={args.watchdog_zone}",
                    f"--project={args.project}",
                ]
            )
        print("watchdog_vm", args.watchdog_vm, "RUNNING", flush=True)
    else:
        print("WARN: --watchdog-zone unset; skipped watchdog VM start", flush=True)

    remote = (
        "sudo mkdir -p /opt/usersim_fm && "
        "sudo touch /opt/usersim_fm/WATCHDOG_ARMED && "
        "sudo chmod 666 /opt/usersim_fm/WATCHDOG_ARMED && "
        "if [ -f /opt/usersim_fm/scripts/usersim-floor-befm.service ]; then "
        "sudo cp /opt/usersim_fm/scripts/usersim-floor-befm.service /etc/systemd/system/; "
        "sudo systemctl daemon-reload; "
        "sudo systemctl enable usersim-floor-befm.service; "
        "fi; "
        "echo ARMED"
    )
    sh(
        g
        + [
            "ssh",
            args.vm,
            f"--zone={args.zone}",
            f"--project={args.project}",
            "--tunnel-through-iap",
            f"--command={remote}",
        ]
    )
    print("PREFLIGHT_OK", args.vm, "spot-watch=true systemd=enabled WATCHDOG_ARMED", flush=True)


if __name__ == "__main__":
    sys.exit(main())
