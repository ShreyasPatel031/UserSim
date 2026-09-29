#!/bin/bash
# Completion monitor for SimBench SFT training
# Runs alongside training, waits for completion, uploads results, stops VM
#
# This monitor does NOT stop training and does NOT load any model.
# It waits for training to complete, uploads the final adapter, sets labels, and stops the VM.

ROOT=/opt/simbench_train
RESULTS=$ROOT/results
ADAPTERS=$ROOT/adapters/simbench_sft
GCS_BUCKET=gs://ai-studio-bucket-347838016394-us-east1/usersim-models/simbench_train

exec >> $RESULTS/completion_monitor.log 2>&1
echo "COMPLETION_MONITOR_START $(date -u +%Y-%m-%dT%H:%M:%SZ)"

update_label() {
    local key=$1
    local value=$2
    python3 - "$key" "$value" <<'PY' || true
import sys, json, urllib.request
key, value = sys.argv[1], sys.argv[2]
def meta(path):
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/" + path,
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode()
try:
    token = json.loads(meta("instance/service-accounts/default/token"))["access_token"]
    project = meta("project/project-id")
    zone = meta("instance/zone").rsplit("/", 1)[-1]
    name = meta("instance/name")
    url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{name}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        inst = json.loads(resp.read().decode())
    labels = dict(inst.get("labels") or {})
    labels[key] = value
    body = json.dumps({"labels": labels, "labelFingerprint": inst["labelFingerprint"]}).encode()
    post = urllib.request.Request(url + "/setLabels", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(post, timeout=20) as resp:
        resp.read()
    print(f"LABEL_SET: {key}={value}")
except Exception as e:
    print(f"LABEL_ERROR: {key}={value} failed: {e}")
PY
}

stop_vm() {
    echo "STOP_VM_REQUEST $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    python3 - <<'PY' || true
import json, urllib.request
def meta(path):
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/" + path,
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode()
try:
    token = json.loads(meta("instance/service-accounts/default/token"))["access_token"]
    project = meta("project/project-id")
    zone = meta("instance/zone").rsplit("/", 1)[-1]
    name = meta("instance/name")
    url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{name}/stop"
    req = urllib.request.Request(url, data=b"", method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    print("VM_STOP_OK")
except Exception as e:
    print(f"VM_STOP_ERROR: {e}")
PY
}

find_trainer_pid() {
    pgrep -f "sft_simbench_qlora.py" 2>/dev/null | head -1
}

wait_for_training_completion() {
    echo "WAIT_FOR_TRAINER $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    local trainer_pid=$(find_trainer_pid)
    local wait_count=0
    local max_wait=15  # Wait up to 15 minutes for trainer to appear
    
    while [ -z "$trainer_pid" ] && [ $wait_count -lt $max_wait ]; do
        wait_count=$((wait_count + 1))
        echo "WAIT: No trainer yet, attempt $wait_count/$max_wait"
        sleep 60
        trainer_pid=$(find_trainer_pid)
    done
    
    if [ -z "$trainer_pid" ]; then
        echo "ERROR: No trainer process found after ${max_wait} minutes"
        return 1
    fi
    
    echo "FOUND_TRAINER: PID=$trainer_pid"
    
    while true; do
        if ! kill -0 "$trainer_pid" 2>/dev/null; then
            echo "TRAINER_EXITED: PID=$trainer_pid at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
            break
        fi
        sleep 60
    done
    
    local exit_code=$(cat $RESULTS/train.exit_code 2>/dev/null || echo "unknown")
    echo "TRAIN_EXIT_CODE: $exit_code"
    
    if [ -f "$RESULTS/TRAIN_DONE.json" ]; then
        echo "TRAIN_STATUS: SUCCESS (TRAIN_DONE.json exists)"
        return 0
    elif [ "$exit_code" = "0" ]; then
        echo "TRAIN_STATUS: SUCCESS (exit code 0)"
        return 0
    else
        echo "TRAIN_STATUS: FAILED (exit_code=$exit_code, no TRAIN_DONE.json)"
        return 1
    fi
}

upload_final_results() {
    echo "UPLOAD_FINAL $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    # Upload adapter
    if [ -d "$ADAPTERS" ]; then
        gsutil -m cp -r $ADAPTERS/* $GCS_BUCKET/final/ 2>/dev/null || true
        echo "UPLOAD_OK: adapter"
    fi
    
    # Upload results
    gsutil -m cp $RESULTS/*.json $GCS_BUCKET/results/ 2>/dev/null || true
    gsutil -m cp $RESULTS/*.log $GCS_BUCKET/results/ 2>/dev/null || true
    
    echo "UPLOAD_COMPLETE"
}

main() {
    echo "============================================"
    echo "COMPLETION_MONITOR_MAIN $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "============================================"
    
    if wait_for_training_completion; then
        echo "Training completed successfully"
        upload_final_results
        update_label "usersim-train-state" "done"
        update_label "usersim-do-not-start" "true"
    else
        echo "Training failed or exited abnormally"
        upload_final_results
        update_label "usersim-train-state" "failed"
    fi
    
    echo "MONITOR_COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    stop_vm
}

main "$@"
