#!/usr/bin/env bash
# Psych-101 Qwen floor on GCP. Smoke then full. Resume via scores jsonl.
set -euo pipefail
ROOT="${FM_ROOT:-/opt/usersim_fm}"
export FM_ROOT="$ROOT"
export WATCHDOG_ARMED=1
export WATCHDOG_MARKER="$ROOT/WATCHDOG_ARMED"
export FLOOR_MODEL="${FLOOR_MODEL:-Qwen/Qwen3-8B-Base}"
export MAX_SEQ="${MAX_SEQ:-4096}"
export BATCH_SIZE="${BATCH_SIZE:-4}"
export NUM_SHARDS="${NUM_SHARDS:-1}"
export SHARD_ID="${SHARD_ID:-0}"
export HF_HOME="${HF_HOME:-$ROOT/hf_home}"
mkdir -p "$ROOT/results/qwen3_8b_floor_psych101" "$ROOT/logs" "$HF_HOME"

if [[ -f "$HOME/.cache/huggingface/token" ]]; then
  export HF_TOKEN
  HF_TOKEN="$(cat "$HOME/.cache/huggingface/token")"
  export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
fi

DATA="$ROOT/data/Psych-101-test/prompts_testing_t1.jsonl"
if [[ ! -f "$DATA" ]]; then
  python3 -m pip install -q -U 'huggingface_hub>=1.5.0'
  mkdir -p "$ROOT/data/Psych-101-test"
  hf buckets sync hf://buckets/shreyaspatel/Psych-101-test-bucket "$ROOT/data/Psych-101-test"
fi

RUNNER="$ROOT/scripts/colab_qwen3_8b_floor_psych101_nll.py"
SMOKE="$ROOT/results/qwen3_8b_floor_psych101/SMOKE_OK.json"
LOG="$ROOT/logs/floor_psych101_shard${SHARD_ID}.log"
touch "$WATCHDOG_MARKER"

echo "mode full shard=${SHARD_ID}/${NUM_SHARDS} batch=${BATCH_SIZE} model=${FLOOR_MODEL}" | tee -a "$LOG"
if [[ ! -f "$SMOKE" ]]; then
  echo "PROTOCOL: smoke first" | tee -a "$LOG"
  MODE=smoke SMOKE_N=32 BATCH_SIZE="$BATCH_SIZE" NUM_SHARDS=1 SHARD_ID=0 \
    python3 -u "$RUNNER" >>"$LOG" 2>&1
fi
MODE=full BATCH_SIZE="$BATCH_SIZE" NUM_SHARDS="$NUM_SHARDS" SHARD_ID="$SHARD_ID" \
  python3 -u "$RUNNER" >>"$LOG" 2>&1
