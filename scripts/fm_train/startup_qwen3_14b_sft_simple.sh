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
    REQUIRED_TORCH_VERSION="2.6.0"
    
    if [ ! -d "$TRAIN_VENV" ]; then
        echo "Creating training venv..."
        python3 -m venv $TRAIN_VENV
        source $TRAIN_VENV/bin/activate
        pip install --upgrade pip
        pip install torch==${REQUIRED_TORCH_VERSION}+cu124 --index-url https://download.pytorch.org/whl/cu124
        pip install transformers==4.47.0 datasets accelerate peft bitsandbytes scipy
        pip install huggingface_hub
    else
        source $TRAIN_VENV/bin/activate
        # Check torch version and upgrade if needed
        CURRENT_TORCH=$(python3 -c "import torch; print(torch.__version__.split('+')[0])" 2>/dev/null || echo "0.0.0")
        if [ "$CURRENT_TORCH" != "$REQUIRED_TORCH_VERSION" ]; then
            echo "Upgrading torch from $CURRENT_TORCH to ${REQUIRED_TORCH_VERSION}..."
            pip install torch==${REQUIRED_TORCH_VERSION}+cu124 --index-url https://download.pytorch.org/whl/cu124
        fi
    fi
}

download_latest_checkpoint() {
    echo "Checking for latest checkpoint in GCS..."
    local latest_step=0
    local latest_local_complete=0
    
    # Find latest complete local checkpoint
    for ckpt in $ADAPTERS/checkpoint-*/; do
        if [ -d "$ckpt" ]; then
            step=$(basename "$ckpt" | sed 's/checkpoint-//')
            if [ "$step" -gt "$latest_step" ] 2>/dev/null; then
                latest_step=$step
            fi
            # Check if checkpoint is complete
            if [ -f "$ckpt/adapter_model.safetensors" ] && [ -s "$ckpt/adapter_model.safetensors" ] && \
               [ -f "$ckpt/adapter_config.json" ] && [ -f "$ckpt/trainer_state.json" ]; then
                if [ "$step" -gt "$latest_local_complete" ] 2>/dev/null; then
                    latest_local_complete=$step
                fi
            fi
        fi
    done
    echo "Latest local checkpoint: $latest_step (complete: $latest_local_complete)"
    
    local gcs_latest=$(gsutil ls $GCS_BUCKET/ 2>/dev/null | grep -oP 'checkpoint-\K\d+' | sort -rn | head -1)
    echo "Latest GCS checkpoint: ${gcs_latest:-none}"
    
    # Download from GCS if it's newer or local is incomplete
    if [ -n "$gcs_latest" ]; then
        if [ "$gcs_latest" -gt "$latest_local_complete" ] 2>/dev/null; then
            echo "Downloading checkpoint-$gcs_latest from GCS..."
            rm -rf $ADAPTERS/checkpoint-$gcs_latest 2>/dev/null || true
            mkdir -p $ADAPTERS/checkpoint-$gcs_latest
            if gsutil -m cp -r $GCS_BUCKET/checkpoint-$gcs_latest/* $ADAPTERS/checkpoint-$gcs_latest/ 2>>$UPLOAD_LOG; then
                echo "Downloaded checkpoint-$gcs_latest successfully"
                # Verify download
                if [ ! -f "$ADAPTERS/checkpoint-$gcs_latest/adapter_model.safetensors" ]; then
                    echo "ERROR: Download incomplete - missing adapter_model.safetensors"
                fi
            else
                echo "ERROR: Failed to download checkpoint-$gcs_latest from GCS"
            fi
        fi
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

start_checkpoint_uploader() {
    echo "Starting background checkpoint uploader..."
    cat > /tmp/checkpoint_uploader.sh << 'UPLOADER_EOF'
#!/bin/bash
ROOT=/opt/usersim_fm
ADAPTERS=$ROOT/adapters/qwen3_14b_sft
GCS_BUCKET=gs://ai-studio-bucket-347838016394-us-east1/usersim-models/qwen3_14b_sft
UPLOAD_LOG=$ROOT/results/qwen3_14b_sft/checkpoint_upload.log
INTERVAL_SECONDS=180

mkdir -p "$(dirname "$UPLOAD_LOG")"
exec >> "$UPLOAD_LOG" 2>&1
echo "CHECKPOINT_UPLOADER_START $(date -u +%Y-%m-%dT%H:%M:%SZ)"

is_checkpoint_complete() {
    local ckpt_dir="$1"
    [ -f "$ckpt_dir/adapter_model.safetensors" ] && \
    [ -f "$ckpt_dir/adapter_config.json" ] && \
    [ -f "$ckpt_dir/trainer_state.json" ] && \
    [ -s "$ckpt_dir/adapter_model.safetensors" ] && \
    [ -s "$ckpt_dir/adapter_config.json" ]
}

gcs_checkpoint_exists() {
    local step="$1"
    gsutil -q stat "$GCS_BUCKET/checkpoint-$step/adapter_model.safetensors" 2>/dev/null
}

upload_checkpoint() {
    local ckpt_dir="$1"
    local step="$2"
    echo "UPLOADING checkpoint-$step at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    local files_to_upload="adapter_model.safetensors adapter_config.json trainer_state.json optimizer.pt scheduler.pt rng_state.pth training_args.bin"
    local success=true
    for f in $files_to_upload; do
        if [ -f "$ckpt_dir/$f" ]; then
            if ! gsutil cp "$ckpt_dir/$f" "$GCS_BUCKET/checkpoint-$step/$f" 2>&1; then
                echo "ERROR: Failed to upload $f"
                success=false
            fi
        fi
    done
    if $success; then
        echo "UPLOAD_OK checkpoint-$step"
    else
        echo "UPLOAD_PARTIAL checkpoint-$step"
    fi
}

while true; do
    if [ -d "$ADAPTERS" ]; then
        for ckpt_dir in "$ADAPTERS"/checkpoint-*/; do
            [ -d "$ckpt_dir" ] || continue
            step=$(basename "$ckpt_dir" | sed 's/checkpoint-//')
            [ "$step" -gt 0 ] 2>/dev/null || continue
            is_checkpoint_complete "$ckpt_dir" || continue
            gcs_checkpoint_exists "$step" && continue
            upload_checkpoint "$ckpt_dir" "$step"
        done
    fi
    sleep "$INTERVAL_SECONDS"
done
UPLOADER_EOF
    chmod +x /tmp/checkpoint_uploader.sh
    # Run as root to be able to read all checkpoint files
    nohup /tmp/checkpoint_uploader.sh &
    echo "Checkpoint uploader started with PID $!"
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
    if sudo -u box gsutil cp "$local_adapter" "$final_gcs" 2>> $UPLOAD_ERROR_LOG; then
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
        sudo -u box gsutil cp "$local_config" "$GCS_BUCKET/final/adapter_config.json" 2>> $UPLOAD_ERROR_LOG || true
    fi
    
    for f in $RESULTS/*.json $RESULTS/*.log; do
        [ -f "$f" ] && gsutil cp "$f" "$GCS_BUCKET/results/" 2>> $UPLOAD_ERROR_LOG || true
    done
}

find_trainer_pid() {
    pgrep -f "sft_qwen3_14b_qlora.py" 2>/dev/null | head -1
}

# Wait up to 15 minutes for trainer to appear (allows for venv setup, checkpoint download, model load)
MAX_WAIT_MINUTES=15
wait_count=0
trainer_pid=$(find_trainer_pid)

while [ -z "$trainer_pid" ] && [ $wait_count -lt $MAX_WAIT_MINUTES ]; do
    wait_count=$((wait_count + 1))
    echo "WAIT: No trainer yet, attempt $wait_count/$MAX_WAIT_MINUTES ($(date -u +%H:%M:%S))"
    sleep 60
    trainer_pid=$(find_trainer_pid)
done

if [ -z "$trainer_pid" ]; then
    echo "ERROR: No trainer after waiting ${MAX_WAIT_MINUTES} minutes"
    update_label "usersim-train-state" "failed"
    stop_vm
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
    
    start_checkpoint_uploader
    start_completion_monitor
    
    run_training
    local exit_code=$?
    
    echo "Training exited with code $exit_code"
    exit $exit_code
}

main "$@"
