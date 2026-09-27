#!/bin/bash
# Background checkpoint uploader for Qwen3-14B SFT training
# Runs CPU-only, uploads new complete checkpoints to GCS every few minutes.
# Runs as the trainer's user (box) to avoid permission issues.

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
    
    local files_to_upload=(
        "adapter_model.safetensors"
        "adapter_config.json"
        "trainer_state.json"
        "optimizer.pt"
        "scheduler.pt"
        "rng_state.pth"
        "training_args.bin"
    )
    
    local success=true
    for f in "${files_to_upload[@]}"; do
        if [ -f "$ckpt_dir/$f" ]; then
            if ! gsutil cp "$ckpt_dir/$f" "$GCS_BUCKET/checkpoint-$step/$f" 2>&1; then
                echo "ERROR: Failed to upload $f"
                success=false
            fi
        fi
    done
    
    if [ -f "$ckpt_dir/README.md" ]; then
        gsutil cp "$ckpt_dir/README.md" "$GCS_BUCKET/checkpoint-$step/" 2>/dev/null || true
    fi
    
    if $success; then
        echo "UPLOAD_OK checkpoint-$step"
    else
        echo "UPLOAD_PARTIAL checkpoint-$step (some files failed)"
    fi
}

main() {
    while true; do
        if [ ! -d "$ADAPTERS" ]; then
            sleep "$INTERVAL_SECONDS"
            continue
        fi
        
        for ckpt_dir in "$ADAPTERS"/checkpoint-*/; do
            [ -d "$ckpt_dir" ] || continue
            
            step=$(basename "$ckpt_dir" | sed 's/checkpoint-//')
            [ "$step" -gt 0 ] 2>/dev/null || continue
            
            if ! is_checkpoint_complete "$ckpt_dir"; then
                continue
            fi
            
            if gcs_checkpoint_exists "$step"; then
                continue
            fi
            
            upload_checkpoint "$ckpt_dir" "$step"
        done
        
        sleep "$INTERVAL_SECONDS"
    done
}

main "$@"
