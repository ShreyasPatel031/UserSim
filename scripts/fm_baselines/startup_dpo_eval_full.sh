#!/bin/bash
# Full startup script for DPO evaluation VM (fm-score-dpo-l4)
# Handles CUDA driver installation on Ubuntu
set -e

exec > >(tee -a /var/log/startup.log) 2>&1
echo "[$(date)] Starting DPO evaluation setup"

GCS_BUCKET=gs://ai-studio-bucket-347838016394-us-east1/usersim-models
WORK=/home/ubuntu/eval_work
LOG=$WORK/eval.log
START_TIME=$(date +%s)
MAX_SECONDS=$((150 * 60))  # 2.5 hours

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

# Install CUDA drivers
install_cuda() {
    if nvidia-smi &>/dev/null; then
        log "NVIDIA drivers already installed"
        nvidia-smi
        return 0
    fi
    
    log "Installing NVIDIA drivers and CUDA..."
    
    # Add NVIDIA repo
    apt-get update -qq
    apt-get install -y -qq linux-headers-$(uname -r) build-essential
    
    # Install NVIDIA driver
    apt-get install -y -qq nvidia-driver-535 nvidia-cuda-toolkit
    
    # Verify installation
    if nvidia-smi &>/dev/null; then
        log "NVIDIA drivers installed successfully"
        nvidia-smi
    else
        log "WARNING: nvidia-smi failed, may need reboot"
    fi
}

# Setup Python environment
setup_python() {
    log "Setting up Python environment..."
    
    # Install Python and pip
    apt-get install -y -qq python3-pip python3-venv
    
    # Create work directory
    mkdir -p $WORK
    cd $WORK
    
    # Install PyTorch with CUDA
    log "Installing PyTorch..."
    pip3 install --quiet torch==2.5.1+cu124 --index-url https://download.pytorch.org/whl/cu124 2>/dev/null || \
    pip3 install --quiet torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121
    
    # Install ML packages
    log "Installing ML packages..."
    pip3 install --quiet transformers==4.51.3 peft==0.15.2 bitsandbytes==0.45.5 accelerate==1.6.0 \
        datasets huggingface_hub scipy numpy
    
    log "Python setup complete"
}

# Download scripts and data
download_scripts() {
    log "Downloading evaluation scripts..."
    cd $WORK
    
    # Download eval scripts
    gsutil -q cp $GCS_BUCKET/qwen3_14b_sft_dpo400/scripts/eval_unseen40_dist.py . || true
    gsutil -q cp $GCS_BUCKET/qwen3_14b_sft_dpo400/scripts/score_unseen40_dist.py . || true
    
    # Download SimBench kit
    mkdir -p simbench
    gsutil -m -q cp -r $GCS_BUCKET/simbench_kit/* simbench/ || {
        log "SimBench kit download failed, will skip SimBench"
    }
    
    log "Scripts downloaded"
}

# Run unseen40 evaluation
run_unseen40() {
    log "=== PART A: UNSEEN40 DISTRIBUTION EVAL ==="
    cd $WORK
    mkdir -p unseen40_results
    
    DPO_ADAPTER="$GCS_BUCKET/qwen3_14b_sft_dpo400/checkpoint-240/"
    SFT_ADAPTER="$GCS_BUCKET/qwen3_14b_sft/checkpoint-600/"
    
    # Run DPO-240
    if check_budget && [ -f eval_unseen40_dist.py ]; then
        log "Running DPO-240 on unseen40..."
        python3 eval_unseen40_dist.py \
            --model Qwen/Qwen3-14B \
            --lora "$DPO_ADAPTER" \
            --name dpo-240 \
            --out unseen40_results 2>&1 | tee -a $LOG || log "DPO-240 failed"
    fi
    
    # Run zero-shot
    if check_budget && [ -f eval_unseen40_dist.py ]; then
        log "Running zero-shot on unseen40..."
        python3 eval_unseen40_dist.py \
            --model Qwen/Qwen3-14B \
            --name zero-shot \
            --out unseen40_results 2>&1 | tee -a $LOG || log "zero-shot failed"
    fi
    
    # Run checkpoint-600
    if check_budget && [ -f eval_unseen40_dist.py ]; then
        log "Running checkpoint-600 on unseen40..."
        python3 eval_unseen40_dist.py \
            --model Qwen/Qwen3-14B \
            --lora "$SFT_ADAPTER" \
            --name checkpoint-600 \
            --out unseen40_results 2>&1 | tee -a $LOG || log "checkpoint-600 failed"
    fi
    
    # Score all models
    if check_budget && [ -f score_unseen40_dist.py ]; then
        log "Scoring all unseen40 models..."
        python3 score_unseen40_dist.py \
            --results-dir unseen40_results \
            --models zero-shot checkpoint-600 dpo-240 \
            --out unseen40_results/comparison.json 2>&1 | tee -a $LOG || log "Scoring failed"
    fi
}

# Run SimBench evaluation
run_simbench() {
    log "=== PART B: SIMBENCH EVAL ==="
    cd $WORK/simbench
    
    if [ ! -f eval_simbench.py ]; then
        log "SimBench scripts not found, skipping"
        return
    fi
    
    mkdir -p runs
    DPO_ADAPTER="$GCS_BUCKET/qwen3_14b_sft_dpo400/checkpoint-240/"
    
    # Download existing runs
    log "Downloading existing SimBench runs..."
    gsutil -m -q cp -r $GCS_BUCKET/simbench_evals/base_* runs/ 2>/dev/null || true
    gsutil -m -q cp -r $GCS_BUCKET/simbench_evals/ckpt400_* runs/ 2>/dev/null || true
    gsutil -m -q cp -r $GCS_BUCKET/simbench_evals/ckpt600_* runs/ 2>/dev/null || true
    
    # Fix nested directory structure
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
            --out runs/dpo240_pilot497 2>&1 | tee -a $LOG || log "pilot497 failed"
    fi
    
    # Run DPO-240 logprob on heldout1426
    if check_budget; then
        log "Running DPO-240 logprob on heldout1426..."
        python3 eval_simbench.py \
            --items items/heldout1426.jsonl \
            --adapter "$DPO_ADAPTER" \
            --out runs/dpo240_heldout1426 2>&1 | tee -a $LOG || log "heldout1426 failed"
    fi
    
    # Run DPO-240 verbalized on pilot497
    if check_budget; then
        log "Running DPO-240 verbalized on pilot497..."
        python3 eval_simbench.py \
            --items items/pilot497.jsonl \
            --adapter "$DPO_ADAPTER" \
            --verbalized \
            --out runs/dpo240_pilot497_verb 2>&1 | tee -a $LOG || log "verbalized failed"
    fi
    
    # Run compare.py --protocol
    if check_budget; then
        log "Running compare.py --protocol..."
        python3 compare.py --protocol --runs-dir runs \
            --models base ckpt400 ckpt600 dpo240 2>&1 | tee $WORK/compare_protocol.txt | tee -a $LOG || log "compare failed"
    fi
}

# Upload results
upload_results() {
    log "=== UPLOADING RESULTS ==="
    cd $WORK
    
    # Upload unseen40 results
    log "Uploading unseen40 results..."
    gsutil -m cp -r unseen40_results/* \
        $GCS_BUCKET/qwen3_14b_sft_dpo400/evals_unseen40/ 2>&1 | tee -a $LOG || true
    
    # Upload SimBench DPO results
    log "Uploading SimBench DPO results..."
    for run in dpo240_pilot497 dpo240_heldout1426 dpo240_pilot497_verb; do
        if [ -d "simbench/runs/$run" ]; then
            gsutil -m cp -r "simbench/runs/$run" \
                "$GCS_BUCKET/simbench_evals/" 2>&1 | tee -a $LOG || true
        fi
    done
    
    # Upload compare output
    if [ -f "compare_protocol.txt" ]; then
        gsutil cp compare_protocol.txt \
            $GCS_BUCKET/simbench_evals/ 2>&1 | tee -a $LOG || true
    fi
    
    # Upload log
    gsutil cp $LOG $GCS_BUCKET/qwen3_14b_sft_dpo400/evals_unseen40/eval.log 2>&1 || true
}

# Cleanup and self-delete
cleanup() {
    ELAPSED=$(($(date +%s) - START_TIME))
    log "=== COMPLETED in $((ELAPSED / 60)) minutes ==="
    
    # Signal completion
    echo "DONE" > $WORK/EVAL_DONE
    gsutil cp $WORK/EVAL_DONE $GCS_BUCKET/qwen3_14b_sft_dpo400/evals_unseen40/EVAL_DONE || true
    
    # Self-delete
    log "Deleting VM..."
    ZONE=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/zone" -H "Metadata-Flavor: Google" | cut -d/ -f4)
    NAME=$(hostname)
    gcloud compute instances delete "$NAME" --zone="$ZONE" --quiet 2>/dev/null || true
}

# Main
main() {
    log "Starting DPO evaluation on $(hostname)"
    log "Budget: 2.5 VM-hours"
    
    mkdir -p $WORK
    cd $WORK
    
    install_cuda
    setup_python
    download_scripts
    
    run_unseen40
    run_simbench
    upload_results
    cleanup
}

main "$@"
