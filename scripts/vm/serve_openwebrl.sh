#!/usr/bin/env bash
# Serve OpenWebRL-4B (Qwen3-VL) on T4. Run on port 8001 when Fara is not loaded.
set -euo pipefail
MODEL="${MODEL:-$HOME/usersim/models/OpenWebRL-4B}"
PORT="${PORT:-8001}"
source "$HOME/usersim/.venv/bin/activate"
exec vllm serve "$MODEL" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --dtype bfloat16 \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.92 \
  --limit-mm-per-prompt image=5 \
  --trust-remote-code \
  --enforce-eager
