#!/bin/bash
# Protocol wrapper: smoke if needed, then full. Used by systemd (foreground).
# Never continue a transformers / --concurrency 1 job.
set -euo pipefail
export FLOOR_MODEL="${FLOOR_MODEL:-Qwen/Qwen3-8B-Base}"
export ROOT="${ROOT:-/opt/usersim_fm}"
export CONCURRENCY="${CONCURRENCY:-32}"
export MAX_NUM_SEQS="${MAX_NUM_SEQS:-64}"
export MAX_TOKENS="${MAX_TOKENS:-64}"
export WORKFLOW_MAX_TOKENS="${WORKFLOW_MAX_TOKENS:-512}"
if [[ "${CONCURRENCY}" -lt 32 ]]; then
  echo "PROTOCOL: CONCURRENCY=${CONCURRENCY} < 32. Refusing the old concurrency-1 path."
  exit 1
fi
export HF_TOKEN="$(cat "$HOME/.cache/huggingface/token" 2>/dev/null || true)"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
if [[ -f /opt/usersim_fm/WATCHDOG_ARMED ]]; then
  export WATCHDOG_ARMED=1
fi
mkdir -p /opt/usersim_fm/results
SMOKE_OK="$ROOT/results/qwen3_8b_base_befm/SMOKE_OK.json"
RUNNER="$ROOT/scripts/colab_qwen3_8b_floor_befm.py"
# Disable the old HF-generate server so a reboot cannot revive concurrency 1.
if [[ -f /opt/usersim_fm/scripts/qwen_openai_server.py ]]; then
  sudo mv /opt/usersim_fm/scripts/qwen_openai_server.py \
    /opt/usersim_fm/scripts/qwen_openai_server.py.DISABLED || true
fi
rm -f /opt/usersim_fm/results/qwen_befm_full.pid /opt/usersim_fm/results/qwen_befm_smoke.pid
if [[ ! -f "$SMOKE_OK" ]]; then
  echo "PROTOCOL: running smoke first"
  MODE=smoke python3 -u "$RUNNER"
fi
exec env MODE=full CONCURRENCY=32 python3 -u "$RUNNER"
