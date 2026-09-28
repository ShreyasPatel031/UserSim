#!/bin/bash
# Startup script for Qwen3-14B QLoRA SFT training
# This script runs the full training pipeline on a Spot g2-standard-8 + 1x L4
#
# Key design:
# - Screens (step 200/400/600) PAUSE training, run eval, then RESUME
# - Step-20 sanity check is run separately on another VM (not here)
# - Trap ensures gate-state is reset on any exit/failure
# - Stale train.exit_code is cleared at boot
# - Skips screens whose SUMMARY.json already exists in GCS

ROOT=/opt/usersim_fm
RESULTS=$ROOT/results/qwen3_14b_sft
ADAPTERS=$ROOT/adapters/qwen3_14b_sft
GCS_BUCKET=gs://ai-studio-bucket-347838016394-us-east1/usersim-models/qwen3_14b_sft
SCREEN_STUDIES="326nv,3muqx,3pcdm,3rvgz,53kjy"
UPLOAD_LOG=$RESULTS/upload_errors.log

mkdir -p $RESULTS $ADAPTERS
exec >> $RESULTS/boot.log 2>&1
echo "BOOT $(date -u +%Y-%m-%dT%H:%M:%SZ)"

cleanup_and_exit() {
    local exit_code=${1:-1}
    echo "EXIT_TRAP triggered with code $exit_code at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    update_label "usersim-gate-state" "exited"
    exit $exit_code
}
trap 'cleanup_and_exit $?' EXIT
trap 'cleanup_and_exit 130' INT TERM

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
    echo "Stopping VM at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
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
    print("VM stop requested")
except Exception as e:
    print(f"vm_stop_failed: {e}")
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

setup_eval_venv() {
    EVAL_VENV=$ROOT/venvs/eval
    if [ ! -d "$EVAL_VENV" ]; then
        echo "Creating eval venv..."
        python3 -m venv $EVAL_VENV
        source $EVAL_VENV/bin/activate
        pip install --upgrade pip
        pip install torch==2.5.1+cu124 --index-url https://download.pytorch.org/whl/cu124
        pip install vllm==0.6.4.post1 transformers datasets huggingface_hub scipy numpy
    else
        source $EVAL_VENV/bin/activate
    fi
}

gcs_exists() {
    local path=$1
    gsutil -q stat "$path" 2>/dev/null
    return $?
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

stop_training() {
    echo "Stopping training gracefully at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    local pid=$(cat $RESULTS/train.pid 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        for i in $(seq 1 30); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$pid" 2>/dev/null; then
            echo "Force killing training..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
    pkill -f "sft_qwen3_14b_qlora.py" 2>/dev/null || true
    sleep 2
    echo "Training stopped"
}

run_screen() {
    local step=$1
    echo "Running screen at step $step at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    CKPT=$ADAPTERS/checkpoint-$step
    if [ ! -d "$CKPT" ]; then
        echo "checkpoint-$step not found; skipping screen"
        return 0
    fi
    
    local summary_gcs="$GCS_BUCKET/screens/step$step/SUMMARY.json"
    if gcs_exists "$summary_gcs"; then
        echo "Screen for step $step already exists in GCS; skipping"
        return 0
    fi
    
    update_label "usersim-gate-state" "screen-$step"
    
    setup_eval_venv
    
    SCREEN_DIR=$ROOT/results/qwen3_14b_sft/screens/step$step
    mkdir -p $SCREEN_DIR
    
    export RESULTS_DIR=$SCREEN_DIR
    export PROBE_MODEL=Qwen/Qwen3-14B-FP8
    export LORA_PATH=$CKPT
    export SMOKE_STUDIES=5
    export TEMPERATURE=0.6
    export TOP_P=0.9
    
    cd /opt/usersim_fm/scripts/fm_baselines
    if ! python3 -u probe_qwen3_14b_acc.py >> $SCREEN_DIR/probe.log 2>&1; then
        echo "Screen $step failed"
        gsutil -m cp -r $SCREEN_DIR/* $GCS_BUCKET/screens/step$step/ 2>>$UPLOAD_LOG || true
        return 1
    fi
    
    gsutil -m cp -r $SCREEN_DIR/* $GCS_BUCKET/screens/step$step/ 2>>$UPLOAD_LOG || true
    
    local passed=true
    python3 - "$SCREEN_DIR" <<'PY'
import json, sys
from pathlib import Path
screen_dir = Path(sys.argv[1])
summary_path = screen_dir / "SUMMARY.json"
if not summary_path.exists():
    print("SUMMARY.json not found")
    sys.exit(1)
summary = json.loads(summary_path.read_text())
W = summary.get("wasserstein_mean")
acc_raw = summary.get("accuracy_raw")
acc_clip = summary.get("accuracy_clipped")
checks = {}
checks["W <= 0.160"] = W is not None and W <= 0.160
checks["acc_raw >= 66.0%"] = acc_raw is not None and acc_raw >= 0.66
checks["acc_clipped >= 70.0%"] = acc_clip is not None and acc_clip >= 0.70
passed = True
for check, ok in checks.items():
    status = "PASS" if ok else "FAIL"
    print(f"  {status}: {check}")
    if not ok:
        passed = False
overall = "PASS" if passed else "FAIL"
print(f"SCREEN_OVERALL: {overall}")
(screen_dir / "GATE.json").write_text(json.dumps({
    "W": W, "acc_raw": acc_raw, "acc_clipped": acc_clip,
    "checks": checks, "passed": passed
}, indent=2) + "\n")
sys.exit(0 if passed else 1)
PY
    local gate_result=$?
    
    update_label "usersim-gate-state" "done-$step"
    return $gate_result
}

early_stop_check() {
    if [ -f "$RESULTS/screens/step200/GATE.json" ]; then
        python3 - <<'PY'
import json, sys
from pathlib import Path
gate = json.loads(Path("/opt/usersim_fm/results/qwen3_14b_sft/screens/step200/GATE.json").read_text())
W = gate.get("W")
acc_clip = gate.get("acc_clipped")
if W is not None and W > 0.20:
    print(f"EARLY_STOP: W={W:.3f} > 0.20")
    sys.exit(1)
if acc_clip is not None and acc_clip < 0.65:
    print(f"EARLY_STOP: acc_clipped={acc_clip:.1%} < 65%")
    sys.exit(1)
print("Step 200 passes early stop check")
PY
        return $?
    fi
    return 0
}

find_latest_checkpoint() {
    local latest_step=0
    for ckpt in $ADAPTERS/checkpoint-*/; do
        if [ -d "$ckpt" ]; then
            step=$(basename "$ckpt" | sed 's/checkpoint-//')
            if [ "$step" -gt "$latest_step" ] 2>/dev/null; then
                latest_step=$step
            fi
        fi
    done
    for ckpt_step in $(gsutil ls $GCS_BUCKET/ 2>/dev/null | grep -oP 'checkpoint-\K\d+' | sort -rn | head -1); do
        if [ "$ckpt_step" -gt "$latest_step" ] 2>/dev/null; then
            echo "Downloading checkpoint-$ckpt_step from GCS..."
            mkdir -p $ADAPTERS/checkpoint-$ckpt_step
            gsutil -m cp -r $GCS_BUCKET/checkpoint-$ckpt_step/* $ADAPTERS/checkpoint-$ckpt_step/ 2>>$UPLOAD_LOG || true
            latest_step=$ckpt_step
        fi
        break
    done
    echo $latest_step
}

main() {
    if [ -f "$RESULTS/TRAIN_DONE.json" ]; then
        echo "TRAIN_DONE exists; running final upload and stopping"
        upload_final_results
        update_label "usersim-train-state" "done"
        stop_vm
        trap - EXIT
        exit 0
    fi
    
    rm -f $RESULTS/train.exit_code
    
    if ! wait_for_gpu; then
        echo "GPU wait failed"
        exit 1
    fi
    
    setup_train_venv
    
    update_label "usersim-train-state" "running"
    update_label "usersim-gate-state" "idle"
    
    local last_screen_done=0
    
    for step in 200 400 600; do
        if gcs_exists "$GCS_BUCKET/screens/step$step/SUMMARY.json"; then
            last_screen_done=$step
        fi
    done
    echo "Last screen completed: $last_screen_done"
    
    while true; do
        run_training &
        TRAIN_PID=$!
        echo "Training PID: $TRAIN_PID"
        echo $TRAIN_PID > $RESULTS/train.pid
        
        local screen_to_run=0
        while kill -0 $TRAIN_PID 2>/dev/null; do
            for step in 200 400 600; do
                if [ $step -le $last_screen_done ]; then
                    continue
                fi
                CKPT=$ADAPTERS/checkpoint-$step
                if [ -d "$CKPT" ] && [ -f "$CKPT/adapter_config.json" ]; then
                    echo "Checkpoint $step ready; will stop training for screen"
                    screen_to_run=$step
                    break 2
                fi
            done
            sleep 30
        done
        
        if [ $screen_to_run -gt 0 ]; then
            stop_training
            
            echo "Uploading checkpoint-$screen_to_run to GCS before screen..."
            gsutil -m cp -r $ADAPTERS/checkpoint-$screen_to_run/* $GCS_BUCKET/checkpoint-$screen_to_run/ 2>>$UPLOAD_LOG || true
            
            if ! run_screen $screen_to_run; then
                echo "Screen $screen_to_run failed pass bar"
            fi
            
            last_screen_done=$screen_to_run
            
            if [ $screen_to_run -eq 200 ]; then
                if ! early_stop_check; then
                    echo "EARLY_STOP triggered at step 200"
                    update_label "usersim-train-state" "early-stop"
                    update_label "usersim-do-not-start" "true"
                    stop_vm
                    trap - EXIT
                    exit 0
                fi
            fi
            
            if [ $screen_to_run -eq 600 ]; then
                echo "Training complete; running final upload"
                upload_final_results
                update_label "usersim-train-state" "done"
                update_label "usersim-do-not-start" "true"
                stop_vm
                trap - EXIT
                exit 0
            fi
            
            echo "Resuming training after screen $screen_to_run..."
            continue
        fi
        
        wait $TRAIN_PID || true
        local exit_code=$(cat $RESULTS/train.exit_code 2>/dev/null || echo "unknown")
        
        if [ -f "$RESULTS/TRAIN_DONE.json" ]; then
            echo "Training completed successfully"
            if [ $last_screen_done -lt 600 ]; then
                run_screen 600 || true
            fi
            upload_final_results
            update_label "usersim-train-state" "done"
            stop_vm
            trap - EXIT
            exit 0
        fi
        
        echo "Training exited with code $exit_code; will attempt resume"
        sleep 10
    done
}

upload_final_results() {
    echo "Uploading final results at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    if [ -d "$ADAPTERS" ]; then
        echo "Uploading final adapter (only loose files, not checkpoint subdirs)..."
        for f in $ADAPTERS/*.json $ADAPTERS/*.safetensors $ADAPTERS/*.txt; do
            if [ -f "$f" ]; then
                gsutil cp "$f" $GCS_BUCKET/final/ 2>>$UPLOAD_LOG || true
            fi
        done
    fi
    
    gsutil -m cp $RESULTS/*.json $GCS_BUCKET/results/ 2>>$UPLOAD_LOG || true
    gsutil -m cp $RESULTS/*.log $GCS_BUCKET/results/ 2>>$UPLOAD_LOG || true
    
    echo "Final upload complete"
}

main "$@"
