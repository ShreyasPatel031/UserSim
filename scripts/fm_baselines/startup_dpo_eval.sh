#!/bin/bash
# Startup script for DPO evaluation VM (fm-score-dpo-l4)
# Hard budget: 2.5 VM-hours
# Runs: unseen40 distribution eval + SimBench eval for DPO-240
set -e

GCS_BUCKET=gs://ai-studio-bucket-347838016394-us-east1/usersim-models
WORK=/home/box/eval_work
LOG=$WORK/eval.log
START_TIME=$(date +%s)
MAX_SECONDS=$((150 * 60))  # 2.5 hours = 150 minutes

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a $LOG
}

check_budget() {
    local elapsed=$(($(date +%s) - START_TIME))
    local remaining=$((MAX_SECONDS - elapsed))
    if [ $remaining -lt 300 ]; then
        log "WARNING: Less than 5 minutes remaining in budget"
        return 1
    fi
    log "Time used: $((elapsed / 60))m, remaining: $((remaining / 60))m"
    return 0
}

# Install drivers if needed
setup_cuda() {
    if ! nvidia-smi &>/dev/null; then
        log "Installing CUDA drivers..."
        sudo apt-get update -qq
        sudo apt-get install -y -qq nvidia-driver-535 nvidia-cuda-toolkit
        log "CUDA installed, may need reboot"
    fi
    nvidia-smi
}

# Setup environment
setup_env() {
    mkdir -p $WORK
    cd $WORK
    
    # Install Python packages
    log "Installing Python packages..."
    pip3 install -q torch==2.5.1+cu124 --index-url https://download.pytorch.org/whl/cu124 2>/dev/null || \
    pip3 install -q torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121
    pip3 install -q transformers==4.51.3 peft==0.15.2 bitsandbytes==0.45.5 accelerate==1.6.0 \
        datasets huggingface_hub scipy numpy
    
    # Download eval scripts from GCS (committed to repo)
    log "Downloading evaluation scripts..."
    gsutil -q cp $GCS_BUCKET/qwen3_14b_sft_dpo400/scripts/*.py $WORK/ 2>/dev/null || true
    
    # Also download SimBench eval kit
    mkdir -p $WORK/simbench
    gsutil -q cp -r $GCS_BUCKET/simbench_kit/* $WORK/simbench/ 2>/dev/null || {
        log "SimBench kit not found in GCS, using bundled version"
    }
}

# Part A: Unseen40 with stored distributions
run_unseen40() {
    log "=== PART A: UNSEEN40 DISTRIBUTION EVAL ==="
    mkdir -p $WORK/unseen40_results
    
    DPO_ADAPTER="$GCS_BUCKET/qwen3_14b_sft_dpo400/checkpoint-240/"
    SFT_ADAPTER="$GCS_BUCKET/qwen3_14b_sft/checkpoint-600/"
    
    # Run DPO-240
    if check_budget; then
        log "Running DPO-240 on unseen40..."
        python3 eval_unseen40_dist.py \
            --model Qwen/Qwen3-14B \
            --lora "$DPO_ADAPTER" \
            --name dpo-240 \
            --out $WORK/unseen40_results 2>&1 | tee -a $LOG
    fi
    
    # Run zero-shot (need distributions for calibration check)
    if check_budget; then
        log "Running zero-shot on unseen40..."
        python3 eval_unseen40_dist.py \
            --model Qwen/Qwen3-14B \
            --name zero-shot \
            --out $WORK/unseen40_results 2>&1 | tee -a $LOG
    fi
    
    # Run checkpoint-600 
    if check_budget; then
        log "Running checkpoint-600 on unseen40..."
        python3 eval_unseen40_dist.py \
            --model Qwen/Qwen3-14B \
            --lora "$SFT_ADAPTER" \
            --name checkpoint-600 \
            --out $WORK/unseen40_results 2>&1 | tee -a $LOG
    fi
    
    # Score all models
    if check_budget; then
        log "Scoring all unseen40 models..."
        python3 score_unseen40_dist.py \
            --results-dir $WORK/unseen40_results \
            --models zero-shot checkpoint-600 dpo-240 \
            --out $WORK/unseen40_results/comparison.json 2>&1 | tee -a $LOG
    fi
}

# Part B: SimBench eval for DPO-240
run_simbench() {
    log "=== PART B: SIMBENCH EVAL ==="
    cd $WORK/simbench
    mkdir -p runs
    
    DPO_ADAPTER="$GCS_BUCKET/qwen3_14b_sft_dpo400/checkpoint-240/"
    
    # Download existing base/ckpt400/ckpt600 runs
    log "Downloading existing SimBench runs..."
    gsutil -m cp -r $GCS_BUCKET/simbench_evals/base_* runs/ 2>/dev/null || true
    gsutil -m cp -r $GCS_BUCKET/simbench_evals/ckpt400_* runs/ 2>/dev/null || true
    gsutil -m cp -r $GCS_BUCKET/simbench_evals/ckpt600_* runs/ 2>/dev/null || true
    
    # Fix nested directory structure from gsutil
    for d in runs/*/; do
        name=$(basename "$d")
        if [ -d "${d}${name}" ]; then
            mv "${d}${name}/"* "$d" 2>/dev/null || true
            rmdir "${d}${name}" 2>/dev/null || true
        fi
    done
    
    # Run DPO-240 logprob on pilot497
    if check_budget; then
        log "Running DPO-240 logprob on pilot497..."
        python3 eval_simbench.py \
            --items items/pilot497.jsonl \
            --adapter "$DPO_ADAPTER" \
            --out runs/dpo240_pilot497 2>&1 | tee -a $LOG
    fi
    
    # Run DPO-240 logprob on heldout1426
    if check_budget; then
        log "Running DPO-240 logprob on heldout1426..."
        python3 eval_simbench.py \
            --items items/heldout1426.jsonl \
            --adapter "$DPO_ADAPTER" \
            --out runs/dpo240_heldout1426 2>&1 | tee -a $LOG
    fi
    
    # Run DPO-240 verbalized on pilot497
    if check_budget; then
        log "Running DPO-240 verbalized on pilot497..."
        python3 eval_simbench.py \
            --items items/pilot497.jsonl \
            --adapter "$DPO_ADAPTER" \
            --verbalized \
            --out runs/dpo240_pilot497_verb 2>&1 | tee -a $LOG
    fi
    
    # Run compare.py --protocol
    if check_budget; then
        log "Running compare.py --protocol..."
        python3 compare.py --protocol --runs-dir runs \
            --models base ckpt400 ckpt600 dpo240 2>&1 | tee $WORK/compare_protocol.txt | tee -a $LOG
    fi
}

# Upload results
upload_results() {
    log "=== UPLOADING RESULTS ==="
    
    # Upload unseen40 results
    log "Uploading unseen40 results..."
    gsutil -m cp -r $WORK/unseen40_results/* \
        $GCS_BUCKET/qwen3_14b_sft_dpo400/evals_unseen40/ 2>&1 | tee -a $LOG
    
    # Upload SimBench DPO results
    log "Uploading SimBench DPO results..."
    for run in dpo240_pilot497 dpo240_heldout1426 dpo240_pilot497_verb; do
        if [ -d "$WORK/simbench/runs/$run" ]; then
            gsutil -m cp -r "$WORK/simbench/runs/$run" \
                "$GCS_BUCKET/simbench_evals/" 2>&1 | tee -a $LOG
        fi
    done
    
    # Upload compare output
    if [ -f "$WORK/compare_protocol.txt" ]; then
        gsutil cp $WORK/compare_protocol.txt \
            $GCS_BUCKET/simbench_evals/ 2>&1 | tee -a $LOG
    fi
    
    # Upload log
    gsutil cp $LOG $GCS_BUCKET/qwen3_14b_sft_dpo400/evals_unseen40/eval.log 2>&1 || true
}

# Main
main() {
    log "Starting DPO evaluation on $(hostname)"
    log "Budget: 2.5 VM-hours"
    
    setup_cuda
    setup_env
    
    run_unseen40
    run_simbench
    upload_results
    
    ELAPSED=$(($(date +%s) - START_TIME))
    log "=== COMPLETED in $((ELAPSED / 60)) minutes ==="
    
    # Signal completion
    echo "DONE" > $WORK/EVAL_DONE
    gsutil cp $WORK/EVAL_DONE $GCS_BUCKET/qwen3_14b_sft_dpo400/evals_unseen40/EVAL_DONE
    
    # Self-delete
    log "Deleting VM..."
    ZONE=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/zone" -H "Metadata-Flavor: Google" | cut -d/ -f4)
    NAME=$(hostname)
    gcloud compute instances delete "$NAME" --zone="$ZONE" --quiet || true
}

main "$@"
