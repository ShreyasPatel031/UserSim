#!/bin/bash
# Colab wrapper: smoke if needed, then full. Conservative: one job, resume, vLLM 32.
set -euo pipefail
export ROOT="${ROOT:-/content/fm_baselines}"
export FLOOR_MODEL="${FLOOR_MODEL:-Qwen/Qwen3-8B-Base}"
export CONCURRENCY="${CONCURRENCY:-32}"
export MAX_NUM_SEQS="${MAX_NUM_SEQS:-64}"
export GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
export WATCHDOG_ARMED=1
export WATCHDOG_MARKER="${WATCHDOG_MARKER:-$ROOT/WATCHDOG_ARMED}"
if [[ "${CONCURRENCY}" -lt 32 ]]; then
  echo "PROTOCOL: CONCURRENCY=${CONCURRENCY} < 32"
  exit 1
fi
mkdir -p "$ROOT/results"
touch "$WATCHDOG_MARKER"
SMOKE_OK="$ROOT/results/qwen3_8b_base_befm/SMOKE_OK.json"
RUNNER="$ROOT/scripts/colab_qwen3_8b_floor_befm.py"
if [[ ! -f "$SMOKE_OK" ]]; then
  echo "PROTOCOL: running smoke first"
  MODE=smoke python3 -u "$RUNNER"
fi
exec env MODE=full python3 -u "$RUNNER"
