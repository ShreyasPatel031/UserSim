#!/usr/bin/env bash
# Start/resume Socrates vLLM shard in the FOREGROUND (systemd-safe).
# Do not nohup here — systemd KillMode would murder the child when the
# wrapper exits.
set -euo pipefail
ROOT=/opt/usersim_fm
export HOME="${HOME:-/home/shreyaspatel}"
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
export HF_TOKEN="$(cat "$HOME/.cache/huggingface/token" 2>/dev/null || true)"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"

mkdir -p "$ROOT"/{scripts,results/socrates,logs}
cd "$ROOT"

# Prefer updated scripts from /tmp when present
for f in socrates_vllm_shard.py socrates_metric.py gate_contract.py; do
  [[ -f /tmp/$f ]] && cp /tmp/$f "$ROOT/scripts/"
done

python3 -c 'import vllm' 2>/dev/null || \
  python3 -m pip install -q -U 'vllm>=0.6.0' transformers datasets huggingface_hub 'jinja2>=3.1.0' scipy numpy pyyaml

nvidia-smi -L || true

# Only kill a prior shard if we are replacing it (avoid clobbering ourselves).
if [[ -f "$ROOT/results/socrates_vllm.pid" ]]; then
  old=$(cat "$ROOT/results/socrates_vllm.pid" || true)
  if [[ -n "${old:-}" && "$old" != "$$" ]] && ps -p "$old" >/dev/null 2>&1; then
    # If that process is already this script's intended worker, leave it —
    # but under systemd we always want a clean foreground start.
    kill "$old" 2>/dev/null || true
    sleep 2
  fi
fi
pkill -f '/opt/usersim_fm/scripts/socrates_vllm_shard.py' 2>/dev/null || true
sleep 1

echo $$ > "$ROOT/results/socrates_vllm.pid"
echo "STARTING_SOCRATES pid=$$" | tee -a "$ROOT/logs/socrates_vllm.log"
exec env SHARD_ID=0 NUM_SHARDS=1 QUANT=fp8 \
  MAX_MODEL_LEN=4096 MAX_NEW_TOKENS=32 MAX_NUM_SEQS=256 GPU_MEM_UTIL=0.92 \
  OUT_DIR="$ROOT/results/socrates" \
  GCS_DEST=gs://usersim-bakeoff-347838016394/fm_baselines/socrates_vllm \
  HF_TOKEN="$HF_TOKEN" HUGGING_FACE_HUB_TOKEN="$HF_TOKEN" \
  python3 -u "$ROOT/scripts/socrates_vllm_shard.py" \
  >>"$ROOT/logs/socrates_vllm.log" 2>&1
