#!/usr/bin/env bash
# One-shot: cut BeFM over to vLLM continuous batching + concurrency 16.
set -euo pipefail
ROOT=/content/fm_baselines
VENV=/opt/usersim_fm/.venv/bin
ADAPTER=$ROOT/models/BeFM1.5-4B
LOG=/opt/usersim_fm/logs/befm_full.log
PIDF=/opt/usersim_fm/results/befm_full.pid

cp /tmp/colab_befm4b_serve_and_eval.py $ROOT/scripts/colab_befm4b_serve_and_eval.py

# Stop old transformers server + eval (avoid matching this script's own argv).
if [[ -f $PIDF ]]; then kill "$(cat $PIDF)" 2>/dev/null || true; fi
pkill -f '/scripts/colab_befm4b_serve_and_eval.py' 2>/dev/null || true
pkill -f 'behaviorbench.eval.main' 2>/dev/null || true
pkill -f 'uvicorn befm_server:app' 2>/dev/null || true
pkill -f 'vllm.entrypoints' 2>/dev/null || true
pkill -f 'vllm serve' 2>/dev/null || true
sleep 5

echo "Installing vLLM..."
$VENV/python -m pip install -q -U 'vllm>=0.6.0'
$VENV/python -c 'import vllm; print("vllm", vllm.__version__)'

TOKEN_FILE=/home/shreyaspatel/.cache/huggingface/token
mkdir -p "$(dirname "$TOKEN_FILE")"
if [[ -f /tmp/hf_token ]]; then cp /tmp/hf_token "$TOKEN_FILE"; fi
export HF_TOKEN
HF_TOKEN="$(cat "$TOKEN_FILE" 2>/dev/null || true)"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"

cd "$ROOT"
nohup env SKIP_INSTALL=1 BEFM_CONCURRENCY=16 BEFM_MAX_NUM_SEQS=64 \
  HF_TOKEN="$HF_TOKEN" HUGGING_FACE_HUB_TOKEN="$HF_TOKEN" \
  $VENV/python -u scripts/colab_befm4b_serve_and_eval.py \
  > "$LOG" 2>&1 &
echo $! > "$PIDF"
echo RESTARTED_BEFM pid="$(cat "$PIDF")"
sleep 15
tail -40 "$LOG" || true
