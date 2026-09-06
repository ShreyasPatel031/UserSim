#!/usr/bin/env bash
set -euo pipefail
ROOT=/opt/usersim_fm
export HOME="${HOME:-/home/shreyaspatel}"
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
export HF_TOKEN="$(cat "$HOME/.cache/huggingface/token" 2>/dev/null || true)"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
export SKIP_INSTALL="${SKIP_INSTALL:-1}"
export MAX_SEQ="${MAX_SEQ:-4096}"
mkdir -p /content "$ROOT"/{results/minitaur,logs,scripts}
sudo ln -sfn "$ROOT" /content/fm_baselines 2>/dev/null || ln -sfn "$ROOT" /content/fm_baselines 2>/dev/null || true
[[ -f /tmp/colab_minitaur_psych101_nll.py ]] && cp /tmp/colab_minitaur_psych101_nll.py "$ROOT/scripts/" && cp /tmp/colab_minitaur_psych101_nll.py /content/fm_baselines/scripts/ || true
pkill -9 -f colab_minitaur_psych101_nll.py 2>/dev/null || true
pkill -9 -f EngineCore 2>/dev/null || true
pkill -9 -f VLLM::EngineCore 2>/dev/null || true
for i in $(seq 1 30); do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
  [[ "${used:-99999}" -lt 200 ]] && break
  sleep 1
done
sleep 2
cd /content/fm_baselines
: > "$ROOT/logs/minitaur_full.log"
nohup env SMOKE_N=0 MAX_SEQ="$MAX_SEQ" SKIP_INSTALL="$SKIP_INSTALL" \
  MAX_NUM_SEQS="${MAX_NUM_SEQS:-32}" CHUNK="${CHUNK:-128}" GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}" QUANT=bitsandbytes \
  HF_TOKEN="$HF_TOKEN" HUGGING_FACE_HUB_TOKEN="$HF_TOKEN" \
  python3 -u scripts/colab_minitaur_psych101_nll.py \
  > "$ROOT/logs/minitaur_full.log" 2>&1 &
echo $! > "$ROOT/results/minitaur_full.pid"
echo RESTARTED_MINITAUR pid="$(cat "$ROOT/results/minitaur_full.pid")" gpu_free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits)"
sleep 5
tail -20 "$ROOT/logs/minitaur_full.log" || true
