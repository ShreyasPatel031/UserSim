#!/bin/bash
# Kill the old transformers server and run the vLLM floor eval.
set -euo pipefail
pkill -f qwen_openai_server.py || true
pkill -f colab_qwen3_8b_floor_befm.py || true
pkill -f 'vllm.entrypoints.openai' || true
sleep 2
export FLOOR_MODEL="${FLOOR_MODEL:-Qwen/Qwen3-8B-Base}"
export ROOT="${ROOT:-/opt/usersim_fm}"
export CONCURRENCY="${CONCURRENCY:-32}"
export MAX_NUM_SEQS="${MAX_NUM_SEQS:-64}"
export MAX_TOKENS="${MAX_TOKENS:-64}"
export WORKFLOW_MAX_TOKENS="${WORKFLOW_MAX_TOKENS:-512}"
export HF_TOKEN="$(cat "$HOME/.cache/huggingface/token" 2>/dev/null || true)"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
mkdir -p /opt/usersim_fm/results
nohup python3 -u /opt/usersim_fm/scripts/colab_qwen3_8b_floor_befm.py \
  > /opt/usersim_fm/results/qwen_befm_full.log 2>&1 &
echo $! > /opt/usersim_fm/results/qwen_befm_full.pid
echo STARTED "$(cat /opt/usersim_fm/results/qwen_befm_full.pid) concurrency=$CONCURRENCY"
sleep 2
tail -n 20 /opt/usersim_fm/results/qwen_befm_full.log || true
