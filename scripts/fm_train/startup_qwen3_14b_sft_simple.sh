#!/bin/bash
# Simplified startup script for Qwen3-14B QLoRA SFT training
# This script resumes training from the latest GCS checkpoint and starts a completion monitor.
# NO SCREENS are run on this VM - screens run on separate VMs.
# The completion monitor waits for training to finish, uploads the final adapter, and stops the VM.

ROOT=/opt/usersim_fm
RESULTS=$ROOT/results/qwen3_14b_sft
ADAPTERS=$ROOT/adapters/qwen3_14b_sft
GCS_BUCKET=gs://ai-studio-bucket-347838016394-us-east1/usersim-models/qwen3_14b_sft
UPLOAD_LOG=$RESULTS/upload_errors.log

mkdir -p $RESULTS $ADAPTERS
exec >> $RESULTS/boot.log 2>&1
echo "BOOT $(date -u +%Y-%m-%dT%H:%M:%SZ)"

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
    print(f"{key}={value}")
except Exception as e:
    print(f"label_update_failed: {e}")
PY
}

wait_for_gpu() {
    for i in $(seq 1 60); do
        nvidia-smi >/dev/null 2>&1 && return 0
        sleep 2
    done
    echo "GPU not available after 2 minutes"
    return 1
}

setup_train_venv() {
    TRAIN_VENV=$ROOT/venvs/train_qwen3_14b
    if [ ! -d "$TRAIN_VENV" ]; then
        echo "Creating training venv..."
        python3 -m venv $TRAIN_VENV
        source $TRAIN_VENV/bin/activate
        pip install --upgrade pip
        pip install torch==2.5.1+cu124 --index-url https://download.pytorch.org/whl/cu124
        pip install transformers==4.47.0 datasets accelerate peft bitsandbytes scipy
        pip install huggingface_hub
    else
        source $TRAIN_VENV/bin/activate
    fi
}

download_latest_checkpoint() {
    echo "Checking for latest checkpoint in GCS..."
    local latest_step=0
    
    for ckpt in $ADAPTERS/checkpoint-*/; do
        if [ -d "$ckpt" ]; then
            step=$(basename "$ckpt" | sed 's/checkpoint-//')
            if [ "$step" -gt "$latest_step" ] 2>/dev/null; then
                latest_step=$step
            fi
        fi
    done
    echo "Latest local checkpoint: $latest_step"
    
    local gcs_latest=$(gsutil ls $GCS_BUCKET/ 2>/dev/null | grep -oP 'checkpoint-\K\d+' | sort -rn | head -1)
    echo "Latest GCS checkpoint: ${gcs_latest:-none}"
    
    if [ -n "$gcs_latest" ] && [ "$gcs_latest" -gt "$latest_step" ] 2>/dev/null; then
        echo "Downloading checkpoint-$gcs_latest from GCS..."
        mkdir -p $ADAPTERS/checkpoint-$gcs_latest
        gsutil -m cp -r $GCS_BUCKET/checkpoint-$gcs_latest/* $ADAPTERS/checkpoint-$gcs_latest/ 2>>$UPLOAD_LOG || true
        echo "Downloaded checkpoint-$gcs_latest"
    fi
}

run_training() {
    echo "Starting training at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    cd /opt/usersim_fm/scripts/fm_train
    
    export ROOT=$ROOT
    export RESULTS_SUBDIR=qwen3_14b_sft
    export SFT_CORPUS=$ROOT/data/socrates_sft.jsonl
    export SFT_MODEL=Qwen/Qwen3-14B
    export SFT_OUT=$ADAPTERS
    export MAX_SEQ=768
    export LR=1e-4
    export MICRO_BATCH=${MICRO_BATCH:-2}
    export GRAD_ACCUM=${GRAD_ACCUM:-16}
    export LORA_R=16
    export MAX_STEPS=600
    export SAVE_STEPS=20
    export LOG_STEPS=5
    export RESUME=1
    export GCS_BUCKET=$GCS_BUCKET
    export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
    
    source $ROOT/venvs/train_qwen3_14b/bin/activate
    python3 -u sft_qwen3_14b_qlora.py >> $RESULTS/train.log 2>&1
    local exit_code=$?
    echo $exit_code > $RESULTS/train.exit_code
    return $exit_code
}

start_completion_monitor() {
    echo "Starting completion monitor..."
    cat > /tmp/completion_monitor.sh << 'MONITOR_EOF'
#!/bin/bash
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
        return 1
    fi
    
    echo "Uploading from $local_adapter..."
    if gsutil cp "$local_adapter" "$final_gcs" 2>> $UPLOAD_ERROR_LOG; then
        echo "UPLOAD_OK: adapter_model.safetensors"
    else
        echo "UPLOAD_ERROR: failed to upload" >> $UPLOAD_ERROR_LOG
    fi
    
    local local_config=""
    if [ -f "$ADAPTERS/adapter_config.json" ]; then
        local_config="$ADAPTERS/adapter_config.json"
    elif [ -d "$ADAPTERS/checkpoint-600" ] && [ -f "$ADAPTERS/checkpoint-600/adapter_config.json" ]; then
        local_config="$ADAPTERS/checkpoint-600/adapter_config.json"
    fi
    
    if [ -n "$local_config" ]; then
        gsutil cp "$local_config" "$GCS_BUCKET/final/adapter_config.json" 2>> $UPLOAD_ERROR_LOG || true
    fi
    
    for f in $RESULTS/*.json $RESULTS/*.log; do
        [ -f "$f" ] && gsutil cp "$f" "$GCS_BUCKET/results/" 2>> $UPLOAD_ERROR_LOG || true
    done
}

find_trainer_pid() {
    pgrep -f "sft_qwen3_14b_qlora.py" 2>/dev/null | head -1
}

sleep 30

trainer_pid=$(find_trainer_pid)
if [ -z "$trainer_pid" ]; then
    echo "WARN: No trainer found, waiting..."
    sleep 120
    trainer_pid=$(find_trainer_pid)
fi

if [ -z "$trainer_pid" ]; then
    echo "ERROR: No trainer after waiting"
    exit 1
fi

echo "FOUND_TRAINER: PID=$trainer_pid"

while kill -0 "$trainer_pid" 2>/dev/null; do
    sleep 60
done

echo "TRAINER_EXITED at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

exit_code=$(cat $RESULTS/train.exit_code 2>/dev/null || echo "unknown")
echo "TRAIN_EXIT_CODE: $exit_code"

if [ -f "$RESULTS/TRAIN_DONE.json" ] || [ "$exit_code" = "0" ]; then
    echo "TRAIN_SUCCESS"
    upload_final_adapter
    update_label "usersim-train-state" "done"
    update_label "usersim-do-not-start" "true"
else
    echo "TRAIN_FAILED"
    update_label "usersim-train-state" "failed"
fi

echo "MONITOR_COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
stop_vm
MONITOR_EOF
    chmod +x /tmp/completion_monitor.sh
    nohup /tmp/completion_monitor.sh &
    echo "Completion monitor started with PID $!"
}

main() {
    if [ -f "$RESULTS/TRAIN_DONE.json" ]; then
        echo "TRAIN_DONE exists; skipping"
        exit 0
    fi
    
    if ! wait_for_gpu; then
        echo "GPU wait failed"
        exit 1
    fi
    
    setup_train_venv
    download_latest_checkpoint
    
    update_label "usersim-train-state" "running"
    update_label "usersim-gate-state" "sft"
    
    start_completion_monitor
    
    run_training
    local exit_code=$?
    
    echo "Training exited with code $exit_code"
    exit $exit_code
}

main "$@"
