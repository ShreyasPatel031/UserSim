#!/usr/bin/env bash
# Serve Fara1.5-4B on T4 (16GB). Tuned for smoke / Mini-2 — not full 262K context.
set -euo pipefail
MODEL="${MODEL:-$HOME/usersim/models/Fara1.5-4B}"
PORT="${PORT:-8000}"
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
