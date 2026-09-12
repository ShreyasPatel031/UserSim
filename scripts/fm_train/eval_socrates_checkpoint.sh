#!/usr/bin/env bash
# Evaluate a mid-training Socrates LoRA checkpoint on unseen studies, gated.
#
# Why this exists: a 2588-step QLoRA epoch is ~36 h on one L4, so committing to
# it blind is how a day gets burned. Scoring an intermediate checkpoint on a few
# unseen studies costs ~30 min and answers whether the run is tracking toward
# W < 0.151 at all. The gate in the runner aborts on junk generations or a score
# that fails to beat uniform guessing, so a pass here is a real signal.
#
# Usage:
#   eval_socrates_checkpoint.sh <checkpoint-dir> [n-unseen-studies]
#
# The adapter must sit on the persistent disk, not /tmp: a Spot preemption
# reboots the VM and wipes /tmp, which would strand the service on restart.
set -euo pipefail

CKPT="${1:?usage: eval_socrates_checkpoint.sh <checkpoint-dir> [n-studies]}"
STUDIES="${2:-6}"
ROOT="${ROOT:-/opt/usersim_fm}"
NAME="$(basename "$CKPT")"

if [[ "$CKPT" == /tmp/* ]]; then
  echo "refusing: $CKPT is under /tmp, which a preemption reboot wipes." >&2
  echo "copy it under $ROOT/adapters/ first." >&2
  exit 2
fi
for f in adapter_config.json adapter_model.safetensors; do
  [[ -f "$CKPT/$f" ]] || { echo "missing $CKPT/$f" >&2; exit 2; }
done

RANK="$(python3 -c "import json;print(json.load(open('$CKPT/adapter_config.json'))['r'])")"
RESULTS_DIR="$ROOT/results/${NAME}_eval"
mkdir -p "$RESULTS_DIR"

echo "checkpoint=$CKPT rank=$RANK studies=$STUDIES results=$RESULTS_DIR"

ROOT="$ROOT" \
RESULTS_DIR="$RESULTS_DIR" \
LORA_PATH="$CKPT" \
FLOOR_MODEL="${FLOOR_MODEL:-Qwen/Qwen3-8B-Base}" \
MAX_LORA_RANK="$RANK" \
SMOKE_STUDIES="$STUDIES" \
MAX_NUM_SEQS="${MAX_NUM_SEQS:-64}" \
CHUNK="${CHUNK:-256}" \
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.88}" \
SKIP_INSTALL="${SKIP_INSTALL:-1}" \
GATE=1 \
MIN_PARSE_RATE="${MIN_PARSE_RATE:-0.98}" \
MIN_BARE_NUMERIC_RATE="${MIN_BARE_NUMERIC_RATE:-0.90}" \
MAX_W_VS_CONTROL="${MAX_W_VS_CONTROL:-0.95}" \
  python3 -u "$ROOT/scripts/colab_qwen3_8b_floor_socrates_vllm.py"

echo "--- verdict ---"
cat "$RESULTS_DIR/GATE.json"
