#!/bin/bash
# Startup script for Qwen3-14B QLoRA DPO training from SFT checkpoint-400
# VM: fm-dpo-socrates-l4 (Spot g2-standard-8 + 1x L4)
#
# - Downloads SFT checkpoint-400 from GCS
# - Generates DPO pairs from SFT corpus
# - Runs DPO training with TRL DPOTrainer
# - Uploads checkpoints every ~30 min to GCS
# - Auto-resumes from latest GCS checkpoint after Spot restart
# - Robust completion monitor stops VM on real completion

ROOT=/opt/usersim_fm
RESULTS=$ROOT/results/qwen3_14b_dpo
ADAPTERS=$ROOT/adapters/qwen3_14b_sft_dpo
SFT_ADAPTER=$ROOT/checkpoints/qwen3_14b_sft/checkpoint-400
GCS_BUCKET=gs://ai-studio-bucket-347838016394-us-east1/usersim-models/qwen3_14b_sft_dpo400
GCS_SFT_CKPT=gs://ai-studio-bucket-347838016394-us-east1/usersim-models/qwen3_14b_sft/checkpoint-400
GCS_SFT_CORPUS=gs://ai-studio-bucket-347838016394-us-east1/usersim-models/qwen3_14b_sft/data/socrates_sft.jsonl
UPLOAD_LOG=$RESULTS/upload_errors.log
SCRIPTS=$ROOT/scripts/fm_train

mkdir -p $RESULTS $ADAPTERS $(dirname $SFT_ADAPTER) $ROOT/data $SCRIPTS
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

stop_vm() {
    echo "STOP_VM $(date -u +%Y-%m-%dT%H:%M:%SZ)"
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

wait_for_gpu() {
    echo "Waiting for GPU..."
    for i in $(seq 1 60); do
        nvidia-smi >/dev/null 2>&1 && { echo "GPU ready"; return 0; }
        sleep 2
    done
    echo "GPU not available after 2 minutes"
    return 1
}

setup_venv() {
    VENV=$ROOT/venvs/dpo
    TORCH_VERSION="2.6.0"
    
    # Check if venv exists and has pip
    if [ ! -f "$VENV/bin/pip" ]; then
        echo "Creating DPO training venv with pip bootstrap..."
        rm -rf $VENV
        python3 -m venv $VENV --without-pip
        # Bootstrap pip for Python 3.9 which doesn't include pip in venv by default
        curl -sS https://bootstrap.pypa.io/pip/3.9/get-pip.py | $VENV/bin/python3
        $VENV/bin/pip install --upgrade pip wheel setuptools
        $VENV/bin/pip install torch==${TORCH_VERSION}+cu124 --index-url https://download.pytorch.org/whl/cu124
        $VENV/bin/pip install 'transformers>=4.51,<4.52' 'peft>=0.12' 'trl>=0.9,<1.0'
        $VENV/bin/pip install datasets accelerate bitsandbytes scipy sentencepiece protobuf
        $VENV/bin/pip install huggingface_hub
    fi
    echo "Venv ready: $($VENV/bin/python3 --version), torch=$($VENV/bin/python3 -c 'import torch; print(torch.__version__)')"
}

download_sft_checkpoint() {
    if [ -f "$SFT_ADAPTER/adapter_model.safetensors" ]; then
        echo "SFT checkpoint already exists locally"
        return 0
    fi
    echo "Downloading SFT checkpoint-400 from GCS..."
    mkdir -p $SFT_ADAPTER
    gsutil -m cp -r $GCS_SFT_CKPT/* $SFT_ADAPTER/ 2>>$UPLOAD_LOG
    if [ ! -f "$SFT_ADAPTER/adapter_model.safetensors" ]; then
        echo "ERROR: Failed to download SFT checkpoint"
        return 1
    fi
    echo "SFT checkpoint downloaded"
}

download_sft_corpus() {
    SFT_CORPUS=$ROOT/data/socrates_sft.jsonl
    if [ -f "$SFT_CORPUS" ] && [ -s "$SFT_CORPUS" ]; then
        echo "SFT corpus already exists locally"
        return 0
    fi
    echo "Downloading SFT corpus from GCS..."
    gsutil cp $GCS_SFT_CORPUS $SFT_CORPUS 2>>$UPLOAD_LOG
    if [ ! -f "$SFT_CORPUS" ] || [ ! -s "$SFT_CORPUS" ]; then
        echo "ERROR: Failed to download SFT corpus"
        return 1
    fi
    echo "SFT corpus downloaded: $(wc -l < $SFT_CORPUS) lines"
}

generate_dpo_pairs() {
    DPO_CORPUS=$ROOT/data/socrates_dpo_pairs.jsonl
    if [ -f "$DPO_CORPUS" ] && [ -s "$DPO_CORPUS" ]; then
        echo "DPO pairs already exist locally: $(wc -l < $DPO_CORPUS) pairs"
        return 0
    fi
    echo "Generating DPO pairs from SFT corpus..."
    $ROOT/venvs/dpo/bin/python3 $SCRIPTS/build_socrates_dpo_pairs.py \
        --sft-corpus $ROOT/data/socrates_sft.jsonl \
        --out $DPO_CORPUS \
        --seed 7
    if [ ! -f "$DPO_CORPUS" ] || [ ! -s "$DPO_CORPUS" ]; then
        echo "ERROR: Failed to generate DPO pairs"
        return 1
    fi
    echo "DPO pairs generated: $(wc -l < $DPO_CORPUS) pairs"
}

download_latest_dpo_checkpoint() {
    echo "Checking for existing DPO checkpoints in GCS..."
    local latest=$(gsutil ls $GCS_BUCKET/ 2>/dev/null | grep -oP 'checkpoint-\K\d+' | sort -rn | head -1)
    if [ -z "$latest" ] || [ "$latest" = "9999" ]; then
        echo "No previous DPO checkpoint found"
        return 0
    fi
    
    local local_latest=0
    for ckpt in $ADAPTERS/checkpoint-*/; do
        if [ -d "$ckpt" ]; then
            step=$(basename "$ckpt" | sed 's/checkpoint-//')
            if [ "$step" -gt "$local_latest" ] 2>/dev/null; then
                local_latest=$step
            fi
        fi
    done
    
    if [ "$latest" -gt "$local_latest" ] 2>/dev/null; then
        echo "Downloading checkpoint-$latest from GCS (local=$local_latest)..."
        mkdir -p $ADAPTERS/checkpoint-$latest
        gsutil -m cp -r $GCS_BUCKET/checkpoint-$latest/* $ADAPTERS/checkpoint-$latest/ 2>>$UPLOAD_LOG
        echo "Downloaded checkpoint-$latest"
    else
        echo "Local checkpoint $local_latest is up to date"
    fi
}

run_training() {
    echo "Starting DPO training at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    export ROOT=$ROOT
    export SFT_MODEL=Qwen/Qwen3-14B
    export SFT_ADAPTER=$SFT_ADAPTER
    export DPO_CORPUS=$ROOT/data/socrates_dpo_pairs.jsonl
    export DPO_OUT=$ADAPTERS
    export GCS_BUCKET=$GCS_BUCKET
    export MAX_SEQ=768
    export LR=5e-6
    export DPO_BETA=0.1
    export MICRO_BATCH=1
    export GRAD_ACCUM=32
    export SAVE_STEPS=10
    export LOG_STEPS=1
    export MAX_STEPS=240
    export WARMUP_RATIO=0.042
    export EPOCHS=1
    export RESUME=1
    export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
    
    cd $SCRIPTS
    $ROOT/venvs/dpo/bin/python3 -u dpo_qwen3_14b_qlora.py >> $RESULTS/train.log 2>&1
    local exit_code=$?
    echo $exit_code > $RESULTS/train.exit_code
    return $exit_code
}

start_completion_monitor() {
    echo "Starting completion monitor..."
    cat > /tmp/dpo_completion_monitor.sh << 'MONITOR_EOF'
#!/bin/bash
ROOT=/opt/usersim_fm
RESULTS=$ROOT/results/qwen3_14b_dpo
ADAPTERS=$ROOT/adapters/qwen3_14b_sft_dpo
GCS_BUCKET=gs://ai-studio-bucket-347838016394-us-east1/usersim-models/qwen3_14b_sft_dpo400

exec >> $RESULTS/completion_monitor.log 2>&1
echo "MONITOR_START $(date -u +%Y-%m-%dT%H:%M:%SZ)"

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
    print(f"LABEL: {key}={value}")
except Exception as e:
    print(f"LABEL_ERROR: {e}")
PY
}

stop_vm() {
    echo "STOP_VM $(date -u +%Y-%m-%dT%H:%M:%SZ)"
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
    # Match the actual Python trainer process, not bash wrappers
    pgrep -f "python3.*dpo_qwen3_14b_qlora.py" 2>/dev/null | head -1
}

# Wait up to 15 minutes for trainer to appear
MAX_WAIT=15
wait_count=0
trainer_pid=$(find_trainer_pid)

while [ -z "$trainer_pid" ] && [ $wait_count -lt $MAX_WAIT ]; do
    wait_count=$((wait_count + 1))
    echo "WAIT: No trainer yet, attempt $wait_count/$MAX_WAIT ($(date -u +%H:%M:%S))"
    sleep 60
    trainer_pid=$(find_trainer_pid)
done

if [ -z "$trainer_pid" ]; then
    echo "ERROR: No trainer after waiting ${MAX_WAIT} minutes"
    update_label "usersim-train-state" "failed"
    stop_vm
    exit 1
fi

echo "FOUND_TRAINER: PID=$trainer_pid"

# Wait for trainer to exit
while kill -0 "$trainer_pid" 2>/dev/null; do
    sleep 60
done

echo "TRAINER_EXITED $(date -u +%Y-%m-%dT%H:%M:%SZ)"

exit_code=$(cat $RESULTS/train.exit_code 2>/dev/null || echo "unknown")
echo "EXIT_CODE: $exit_code"

if [ -f "$RESULTS/TRAIN_DONE.json" ] || [ "$exit_code" = "0" ]; then
    echo "TRAIN_SUCCESS"
    # Final upload
    gsutil -m cp $RESULTS/*.json $GCS_BUCKET/results/ 2>/dev/null || true
    gsutil -m cp $RESULTS/*.log $GCS_BUCKET/results/ 2>/dev/null || true
    update_label "usersim-train-state" "done"
    update_label "usersim-do-not-start" "true"
else
    echo "TRAIN_FAILED"
    update_label "usersim-train-state" "failed"
fi

echo "MONITOR_COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
stop_vm
MONITOR_EOF
    chmod +x /tmp/dpo_completion_monitor.sh
    nohup /tmp/dpo_completion_monitor.sh &
    echo "Completion monitor started PID=$!"
}

main() {
    if [ -f "$RESULTS/TRAIN_DONE.json" ]; then
        echo "TRAIN_DONE exists; stopping VM"
        update_label "usersim-train-state" "done"
        stop_vm
        exit 0
    fi
    
    rm -f $RESULTS/train.exit_code
    
    if ! wait_for_gpu; then
        echo "GPU wait failed"
        exit 1
    fi
    
    setup_venv
    
    if ! download_sft_checkpoint; then
        echo "Failed to get SFT checkpoint"
        exit 1
    fi
    
    if ! download_sft_corpus; then
        echo "Failed to get SFT corpus"
        exit 1
    fi
    
    if ! generate_dpo_pairs; then
        echo "Failed to generate DPO pairs"
        exit 1
    fi
    
    download_latest_dpo_checkpoint
    
    update_label "usersim-train-state" "running"
    
    start_completion_monitor
    
    run_training
    local exit_code=$?
    
    echo "Training exited with code $exit_code"
    exit $exit_code
}

main "$@"
