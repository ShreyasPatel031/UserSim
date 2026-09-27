#!/bin/bash
# Simple completion monitor for Qwen3-14B SFT training
# This monitor does NOT stop training and does NOT load any model.
# It waits for training to complete, uploads the final adapter, sets labels, and stops the VM.

ROOT=/opt/usersim_fm
RESULTS=$ROOT/results/qwen3_14b_sft
ADAPTERS=$ROOT/adapters/qwen3_14b_sft
GCS_BUCKET=gs://ai-studio-bucket-347838016394-us-east1/usersim-models/qwen3_14b_sft
UPLOAD_ERROR_LOG=$RESULTS/monitor_upload_errors.log

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

gcs_exists() {
    gsutil -q stat "$1" 2>/dev/null
}

upload_final_adapter() {
    echo "UPLOAD_FINAL $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    local final_gcs="$GCS_BUCKET/final/adapter_model.safetensors"
    if gcs_exists "$final_gcs"; then
        echo "UPLOAD_SKIP: final adapter already exists in GCS"
        return 0
    fi
    
    local local_adapter=""
    if [ -f "$ADAPTERS/adapter_model.safetensors" ]; then
        local_adapter="$ADAPTERS/adapter_model.safetensors"
    elif [ -d "$ADAPTERS/checkpoint-600" ] && [ -f "$ADAPTERS/checkpoint-600/adapter_model.safetensors" ]; then
        local_adapter="$ADAPTERS/checkpoint-600/adapter_model.safetensors"
    fi
    
    if [ -z "$local_adapter" ]; then
        echo "UPLOAD_ERROR: no final adapter found locally" >> $UPLOAD_ERROR_LOG
        echo "UPLOAD_ERROR: no final adapter found locally"
        return 1
    fi
    
    echo "Uploading from $local_adapter..."
    if gsutil cp "$local_adapter" "$final_gcs" 2>> $UPLOAD_ERROR_LOG; then
        echo "UPLOAD_OK: adapter_model.safetensors"
    else
        echo "UPLOAD_ERROR: failed to upload adapter_model.safetensors" >> $UPLOAD_ERROR_LOG
        echo "UPLOAD_ERROR: failed to upload adapter_model.safetensors"
    fi
    
    local local_config=""
    if [ -f "$ADAPTERS/adapter_config.json" ]; then
        local_config="$ADAPTERS/adapter_config.json"
    elif [ -d "$ADAPTERS/checkpoint-600" ] && [ -f "$ADAPTERS/checkpoint-600/adapter_config.json" ]; then
        local_config="$ADAPTERS/checkpoint-600/adapter_config.json"
    fi
    
    if [ -n "$local_config" ]; then
        if gsutil cp "$local_config" "$GCS_BUCKET/final/adapter_config.json" 2>> $UPLOAD_ERROR_LOG; then
            echo "UPLOAD_OK: adapter_config.json"
        else
            echo "UPLOAD_ERROR: failed to upload adapter_config.json" >> $UPLOAD_ERROR_LOG
        fi
    fi
    
    for f in $RESULTS/*.json $RESULTS/*.log; do
        [ -f "$f" ] && gsutil cp "$f" "$GCS_BUCKET/results/" 2>> $UPLOAD_ERROR_LOG || true
    done
    
    echo "UPLOAD_COMPLETE"
}

find_trainer_pid() {
    pgrep -f "sft_qwen3_14b_qlora.py" 2>/dev/null | head -1
}

wait_for_training_completion() {
    echo "WAIT_FOR_TRAINER $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    local trainer_pid=$(find_trainer_pid)
    if [ -z "$trainer_pid" ]; then
        echo "WARN: No trainer process found at start"
        sleep 60
        trainer_pid=$(find_trainer_pid)
    fi
    
    if [ -z "$trainer_pid" ]; then
        echo "ERROR: No trainer process found after waiting"
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

main() {
    echo "============================================"
    echo "COMPLETION_MONITOR_MAIN $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "============================================"
    
    if wait_for_training_completion; then
        echo "Training completed successfully"
        upload_final_adapter
        update_label "usersim-train-state" "done"
        update_label "usersim-do-not-start" "true"
    else
        echo "Training failed or exited abnormally"
        update_label "usersim-train-state" "failed"
    fi
    
    echo "MONITOR_COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    stop_vm
}

main "$@"
