#!/usr/bin/env bash
# ==============================================================================
# Phase 4 On-Demand L4 GPU Runner (`usersim_core/run_phase4_gemma_probe.sh`)
# ==============================================================================
# Starts `gemma-persona-probe` (`us-central1-c`, `g2-standard-4`, 1x NVIDIA L4 24GB),
# pulls the leak-audited multi-task corpus from `gs://usersim-trace-store-347838016394/usersim_core_v5/qwen_vl_v5/data/`,
# runs `Qwen/Qwen2.5-VL-7B-Instruct` LoRA (`r=32`, `bf16`) training + Val evaluation,
# syncs adapter & metrics to GCS, and ALWAYS stops `gemma-persona-probe` on exit!
# ==============================================================================
set -euo pipefail

PROJECT="project-amer-scs-sandbox"
ZONE="us-central1-c"
VM="gemma-persona-probe"
GCS_BASE="gs://usersim-trace-store-347838016394/usersim_core_v5/qwen_vl_v5"
MAX_TRAIN_ROWS="${1:-1200}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cleanup() {
  echo "=== Stopping $VM ($ZONE) per Shared-VM On-Demand Rule ==="
  gcloud compute instances stop "$VM" --project="$PROJECT" --zone="$ZONE" --quiet || true
}
trap cleanup EXIT

echo "=== [1/4] Starting L4 GPU VM $VM ($ZONE) ==="
gcloud compute instances start "$VM" --project="$PROJECT" --zone="$ZONE"

echo "=== [2/4] Waiting for SSH & NVIDIA L4 GPU readiness ==="
for i in $(seq 1 24); do
  if gcloud compute ssh "$VM" --project="$PROJECT" --zone="$ZONE" --internal-ip --quiet --command="nvidia-smi -L" 2>/dev/null; then
    break
  fi
  sleep 5
done

echo "=== [3/4] Syncing qwen_vl_unified_v5.py & executing Qwen2.5-VL-7B LoRA (r=32) ==="
gcloud compute scp --project="$PROJECT" --zone="$ZONE" --internal-ip --quiet \
  "$REPO_DIR/usersim_core/qwen_vl_unified_v5.py" "$VM:/tmp/qwen_vl_unified_v5.py"

gcloud compute ssh "$VM" --project="$PROJECT" --zone="$ZONE" --internal-ip --quiet --command="
  set -euo pipefail
  PY=''
  for c in /opt/conda/bin/python3 /opt/python/*/bin/python3 /usr/bin/python3; do
    if [ -x \"\$c\" ] && \"\$c\" -c 'import torch; assert torch.cuda.is_available()' 2>/dev/null; then PY=\$c; break; fi
  done
  TORCH=\$(\$PY -c 'import torch; print(torch.__version__.split(\"+\")[0])')
  \$PY -m pip install -q --upgrade transformers peft accelerate pillow scikit-learn qwen-vl-utils \"torch==\$TORCH\" || true

  mkdir -p /tmp/qwen_vl_data /tmp/qwen_vl_run_r32
  gcloud storage cp -q '$GCS_BASE/data/train.jsonl' '$GCS_BASE/data/val.jsonl' /tmp/qwen_vl_data/

  PYTHONUNBUFFERED=1 \$PY /tmp/qwen_vl_unified_v5.py train_eval \
    --model Qwen/Qwen2.5-VL-7B-Instruct \
    --train-jsonl /tmp/qwen_vl_data/train.jsonl \
    --val-jsonl /tmp/qwen_vl_data/val.jsonl \
    --out-dir /tmp/qwen_vl_run_r32 \
    --lora-r 32 \
    --max-train-rows $MAX_TRAIN_ROWS \
    --gcs-dest '$GCS_BASE/runs'

  rm -rf /tmp/qwen_vl_data /tmp/qwen_vl_run_r32
"

echo "=== [4/4] Phase 4 Run Complete! Artifacts saved to $GCS_BASE/runs/ ==="
