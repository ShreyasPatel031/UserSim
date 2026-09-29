#!/bin/bash
# Startup script for SimBench QLoRA SFT training
# Designed for Spot g2-standard-8 + 1x L4 24GB
#
# Key design:
# - Auto-resume from latest GCS checkpoint on Spot preemption
# - Step-50 format gate check
# - GCS checkpoint every 100 steps
# - Labels for monitoring (usersim-train-state, usersim-do-not-start)
#
# Usage:
#   gcloud compute instances create simbench-train-l4 \
#     --zone=<ZONE> \
#     --machine-type=g2-standard-8 \
#     --accelerator=type=nvidia-l4,count=1 \
#     --image-family=pytorch-2-1-cu121-debian-11-py310 \
#     --image-project=deeplearning-platform-release \
#     --boot-disk-size=200GB \
#     --scopes=cloud-platform \
#     --provisioning-model=SPOT \
#     --metadata-from-file=startup-script=startup_simbench_l4.sh \
#     --labels=usersim-train-state=pending,usersim-do-not-start=false

set -e

ROOT=/opt/simbench_train
RESULTS=$ROOT/results
ADAPTERS=$ROOT/adapters/simbench_sft
GCS_BUCKET=gs://ai-studio-bucket-347838016394-us-east1/usersim-models/simbench_train
GCS_DATA=$GCS_BUCKET/data

mkdir -p $ROOT $RESULTS $ADAPTERS
exec >> $RESULTS/boot.log 2>&1
echo "BOOT $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ------------- Label helpers -------------
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
    print(f"LABEL_ERROR: {key}={value} failed: {e}")
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

cleanup_exit() {
    local code=${1:-1}
    echo "EXIT_TRAP code=$code $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    update_label "usersim-train-state" "exited"
    exit $code
}
trap 'cleanup_exit $?' EXIT
trap 'cleanup_exit 130' INT TERM

# ------------- GPU wait -------------
wait_for_gpu() {
    for i in $(seq 1 60); do
        nvidia-smi >/dev/null 2>&1 && return 0
        sleep 2
    done
    echo "GPU not available after 2 minutes"
    return 1
}

# ------------- Setup venv -------------
setup_venv() {
    VENV=$ROOT/venv
    if [ ! -d "$VENV" ]; then
        echo "Creating venv..."
        python3 -m venv $VENV
        source $VENV/bin/activate
        pip install --upgrade pip
        pip install torch==2.5.1+cu124 --index-url https://download.pytorch.org/whl/cu124
        pip install transformers==4.51.3 datasets accelerate peft==0.15.2 bitsandbytes==0.45.5
        pip install huggingface_hub scipy numpy sentence-transformers scikit-learn
    else
        source $VENV/bin/activate
    fi
}

# ------------- Download data -------------
download_data() {
    DATA_DIR=$ROOT/data
    mkdir -p $DATA_DIR
    
    if [ ! -f "$DATA_DIR/armA_humandist/train.jsonl" ]; then
        echo "Downloading training data from GCS..."
        gsutil -m cp -r $GCS_DATA/armA_humandist $DATA_DIR/
    fi
    
    echo "Data ready: $(ls -la $DATA_DIR/armA_humandist/)"
}

# ------------- Download scripts -------------
download_scripts() {
    SCRIPTS_DIR=$ROOT/scripts
    mkdir -p $SCRIPTS_DIR
    
    # Download the trainer script
    gsutil cp $GCS_BUCKET/scripts/sft_simbench_qlora.py $SCRIPTS_DIR/ 2>/dev/null || true
    
    # If not in GCS, use local (for initial deployment)
    if [ ! -f "$SCRIPTS_DIR/sft_simbench_qlora.py" ]; then
        echo "Trainer script not found in GCS, checking local..."
    fi
}

# ------------- Run training -------------
run_training() {
    echo "Starting training $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    source $ROOT/venv/bin/activate
    
    export ROOT=$ROOT
    export GCS_BUCKET=$GCS_BUCKET
    export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
    
    cd $ROOT
    
    # Get loss type from metadata or default
    LOSS_TYPE=${LOSS_TYPE:-ce_kl}
    KL_LAMBDA=${KL_LAMBDA:-0.5}
    MAX_STEPS=${MAX_STEPS:-1000}
    
    python3 $ROOT/scripts/sft_simbench_qlora.py \
        --data $ROOT/data/armA_humandist/train.jsonl \
        --val-data $ROOT/data/armA_humandist/val.jsonl \
        --out $ADAPTERS \
        --loss $LOSS_TYPE \
        --kl-lambda $KL_LAMBDA \
        --max-steps $MAX_STEPS \
        --save-steps 100 \
        --gate-step 50 \
        --resume \
        >> $RESULTS/train.log 2>&1
    
    local exit_code=$?
    echo $exit_code > $RESULTS/train.exit_code
    return $exit_code
}

# ------------- Upload results -------------
upload_results() {
    echo "Uploading results $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    # Upload final adapter
    if [ -d "$ADAPTERS" ]; then
        gsutil -m cp -r $ADAPTERS/* $GCS_BUCKET/final/ 2>/dev/null || true
    fi
    
    # Upload logs and results
    gsutil -m cp $RESULTS/*.json $GCS_BUCKET/results/ 2>/dev/null || true
    gsutil -m cp $RESULTS/*.log $GCS_BUCKET/results/ 2>/dev/null || true
    
    echo "Upload complete"
}

# ------------- Main -------------
main() {
    echo "========================================="
    echo "SIMBENCH_TRAIN_MAIN $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "========================================="
    
    # Check if already done
    if [ -f "$RESULTS/TRAIN_DONE.json" ]; then
        echo "Training already complete"
        upload_results
        update_label "usersim-train-state" "done"
        update_label "usersim-do-not-start" "true"
        stop_vm
        trap - EXIT
        exit 0
    fi
    
    # Wait for GPU
    if ! wait_for_gpu; then
        echo "GPU wait failed"
        exit 1
    fi
    echo "GPU ready: $(nvidia-smi --query-gpu=name --format=csv,noheader)"
    
    # Setup
    setup_venv
    download_data
    download_scripts
    
    update_label "usersim-train-state" "running"
    
    # Run training (with retries for preemption)
    for attempt in 1 2 3; do
        echo "Training attempt $attempt"
        
        if run_training; then
            echo "Training completed successfully"
            upload_results
            update_label "usersim-train-state" "done"
            update_label "usersim-do-not-start" "true"
            stop_vm
            trap - EXIT
            exit 0
        fi
        
        local exit_code=$(cat $RESULTS/train.exit_code 2>/dev/null || echo "unknown")
        echo "Training exited with code $exit_code"
        
        # Check for format gate failure
        if [ -f "$RESULTS/GATE.json" ]; then
            if python3 -c "import json; g=json.load(open('$RESULTS/GATE.json')); exit(0 if g.get('passed') else 1)"; then
                echo "Format gate passed"
            else
                echo "FORMAT_GATE_FAILED - stopping"
                update_label "usersim-train-state" "gate-failed"
                update_label "usersim-do-not-start" "true"
                upload_results
                stop_vm
                trap - EXIT
                exit 1
            fi
        fi
        
        # Brief wait before retry (in case of transient failure)
        sleep 10
    done
    
    echo "All attempts failed"
    update_label "usersim-train-state" "failed"
    upload_results
    stop_vm
}

main "$@"
