#!/usr/bin/env python3
"""Boot Spot L4 VM for format smoke test.

Creates a g2-standard-8 + 1x L4 VM, runs the smoke test, uploads results, deletes VM.
Hard cap: 45 minutes VM time (~$1).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT = os.environ.get("GCP_PROJECT", "project-amer-scs-sandbox")
ZONE_PRIORITY = [
    "us-central1-a", "us-central1-b", "us-central1-c", "us-central1-f",
    "us-east1-b", "us-east1-c", "us-east1-d",
    "us-east4-a", "us-east4-b", "us-east4-c",
]
BUCKET = "ai-studio-bucket-347838016394-us-east1"
CHECKPOINT_PREFIX = "usersim-models/qwen3_14b_distmatch/checkpoint-1400"
OUTPUT_PREFIX = "usersim-models/qwen3_14b_distmatch/smoke_format"

STARTUP_SCRIPT = r'''#!/bin/bash
set -ex

# Mark as running
gcloud compute instances add-labels $(hostname) --zone=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone | cut -d/ -f4) --labels=usersim-train-state=running || true

# Install dependencies
apt-get update
apt-get install -y python3-pip git

# Install PyTorch and ML libs
pip3 install --upgrade pip
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip3 install transformers accelerate bitsandbytes peft datasets huggingface_hub scipy numpy sentencepiece protobuf google-cloud-storage

# Create directories
mkdir -p /opt/usersim_fm/adapters/qwen3_14b_distmatch
mkdir -p /opt/usersim_fm/results/smoke_format

# Download checkpoint from GCS
gsutil -m cp -r gs://{bucket}/{ckpt_prefix}/* /opt/usersim_fm/adapters/qwen3_14b_distmatch/checkpoint-1400/

# Download smoke test script
gsutil cp gs://{bucket}/usersim-models/qwen3_14b_distmatch/smoke_format_script.py /opt/usersim_fm/smoke_test.py

# Set HF cache
export HF_HOME=/opt/usersim_fm/hf_cache
mkdir -p $HF_HOME

# Run smoke test
cd /opt/usersim_fm
timeout 2400 python3 smoke_test.py || true

# Upload results
gsutil -m cp -r /opt/usersim_fm/results/smoke_format/* gs://{bucket}/{output_prefix}/ || true

# Mark as done
gcloud compute instances add-labels $(hostname) --zone=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone | cut -d/ -f4) --labels=usersim-train-state=done,usersim-do-not-start=true || true

# Signal completion
touch /tmp/smoke_done
'''.format(bucket=BUCKET, ckpt_prefix=CHECKPOINT_PREFIX, output_prefix=OUTPUT_PREFIX)


def gcloud(*args, capture=False):
    cmd = ["gcloud", "--project", PROJECT, *args]
    print("+", " ".join(cmd), flush=True)
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    else:
        subprocess.run(cmd, check=True)


def create_vm(name: str, zone: str, spot: bool = True) -> bool:
    """Create the VM. Returns True if successful."""
    args = [
        "compute", "instances", "create", name,
        f"--zone={zone}",
        "--machine-type=g2-standard-8",
        "--accelerator=type=nvidia-l4,count=1",
        "--image-family=pytorch-latest-gpu",
        "--image-project=deeplearning-platform-release",
        "--boot-disk-size=100GB",
        "--boot-disk-type=pd-ssd",
        "--maintenance-policy=TERMINATE",
        f"--metadata=startup-script={STARTUP_SCRIPT}",
        "--scopes=cloud-platform",
        "--labels=usersim-smoke-test=true,usersim-train-state=starting",
    ]
    if spot:
        args.append("--provisioning-model=SPOT")
        args.append("--instance-termination-action=DELETE")
    
    try:
        gcloud(*args)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to create VM in {zone}: {e}", flush=True)
        return False


def delete_vm(name: str, zone: str):
    """Delete the VM and its boot disk."""
    try:
        gcloud("compute", "instances", "delete", name, f"--zone={zone}", "--quiet", "--delete-disks=all")
        print(f"Deleted VM {name}", flush=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to delete VM: {e}", flush=True)


def wait_for_completion(name: str, zone: str, timeout_min: int = 45) -> tuple[bool, float]:
    """Wait for VM to complete. Returns (success, elapsed_minutes)."""
    start = time.time()
    deadline = start + timeout_min * 60
    
    while time.time() < deadline:
        try:
            result = gcloud("compute", "instances", "describe", name, f"--zone={zone}", 
                          "--format=json", capture=True)
            inst = json.loads(result)
            labels = inst.get("labels", {})
            state = labels.get("usersim-train-state", "")
            
            if state == "done":
                elapsed = (time.time() - start) / 60
                print(f"VM completed in {elapsed:.1f} minutes", flush=True)
                return True, elapsed
            elif inst.get("status") == "TERMINATED":
                elapsed = (time.time() - start) / 60
                print(f"VM was preempted after {elapsed:.1f} minutes", flush=True)
                return False, elapsed
            
            print(f"Waiting... state={state} status={inst.get('status')}", flush=True)
        except subprocess.CalledProcessError:
            elapsed = (time.time() - start) / 60
            print(f"VM no longer exists after {elapsed:.1f} minutes", flush=True)
            return False, elapsed
        
        time.sleep(30)
    
    elapsed = (time.time() - start) / 60
    print(f"Timeout after {elapsed:.1f} minutes", flush=True)
    return False, elapsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="fm-smoke-format-l4")
    parser.add_argument("--no-spot", action="store_true", help="Use on-demand instead of Spot")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    print(f"=== Format Smoke Test Boot ===", flush=True)
    print(f"VM: {args.name}, Spot: {not args.no_spot}, Timeout: {args.timeout}m", flush=True)
    
    if args.dry_run:
        print("Dry run - would create VM with startup script:")
        print(STARTUP_SCRIPT)
        return
    
    zone = None
    for z in ZONE_PRIORITY:
        print(f"Trying zone {z}...", flush=True)
        if create_vm(args.name, z, spot=not args.no_spot):
            zone = z
            break
        if args.no_spot:
            break
    
    if not zone:
        print("FAILED: Could not create VM in any zone", flush=True)
        sys.exit(1)
    
    print(f"VM created in {zone}", flush=True)
    
    success, elapsed = wait_for_completion(args.name, zone, args.timeout)
    
    cost = elapsed * (0.98 / 60)
    print(f"\n=== Results ===", flush=True)
    print(f"Success: {success}", flush=True)
    print(f"Elapsed: {elapsed:.1f} minutes", flush=True)
    print(f"Estimated cost: ${cost:.2f}", flush=True)
    
    delete_vm(args.name, zone)
    
    print(f"\nResults should be at: gs://{BUCKET}/{OUTPUT_PREFIX}/", flush=True)


if __name__ == "__main__":
    main()
