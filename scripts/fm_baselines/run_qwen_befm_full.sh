#!/bin/bash
# Protocol wrapper: smoke if needed, then full. Used by systemd (foreground).
set -euo pipefail
export FLOOR_MODEL="${FLOOR_MODEL:-Qwen/Qwen3-8B-Base}"
export ROOT="${ROOT:-/opt/usersim_fm}"
export CONCURRENCY="${CONCURRENCY:-32}"
export MAX_NUM_SEQS="${MAX_NUM_SEQS:-64}"
export MAX_TOKENS="${MAX_TOKENS:-64}"
export WORKFLOW_MAX_TOKENS="${WORKFLOW_MAX_TOKENS:-512}"
export HF_TOKEN="$(cat "$HOME/.cache/huggingface/token" 2>/dev/null || true)"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
if [[ -f /opt/usersim_fm/WATCHDOG_ARMED ]]; then
  export WATCHDOG_ARMED=1
fi
mkdir -p /opt/usersim_fm/results
SMOKE_OK="$ROOT/results/qwen3_8b_base_befm/SMOKE_OK.json"
RUNNER="$ROOT/scripts/colab_qwen3_8b_floor_befm.py"
pkill -f qwen_openai_server.py || true
if [[ ! -f "$SMOKE_OK" ]]; then
  echo "PROTOCOL: running smoke first"
  MODE=smoke python3 -u "$RUNNER"
fi
exec env MODE=full python3 -u "$RUNNER"
