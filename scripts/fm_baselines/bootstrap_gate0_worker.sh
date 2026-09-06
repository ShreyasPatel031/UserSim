#!/usr/bin/env bash
# Bootstrap Gate 0 worker on a GCP GPU VM.
# Usage: bash bootstrap_gate0_worker.sh socrates|minitaur|befm
set -euo pipefail
JOB="${1:?job name: socrates|minitaur|befm}"
ROOT=/opt/usersim_fm
mkdir -p "$ROOT"/{scripts,data,results,logs}
cd "$ROOT"

export HF_TOKEN="${HF_TOKEN:-}"
export HUGGING_FACE_HUB_TOKEN="${HF_TOKEN}"
export PATH="$HOME/.local/bin:$PATH"

python3 -m pip install -q -U pip
python3 -m pip install -q -U 'huggingface_hub>=1.5.0' pyyaml

# HF login if token present
if [[ -n "${HF_TOKEN}" ]]; then
  python3 - <<'PY'
import os
from huggingface_hub import login
login(token=os.environ["HF_TOKEN"], add_to_git_credential=True)
print("hf_login_ok")
PY
fi

case "$JOB" in
  socrates)
    # Full 40-study run — no ALLOW_PARTIAL
    nohup env SMOKE_STUDIES=0 MAX_PER_CELL=0 \
      python3 -u "$ROOT/scripts/colab_socrates_wass.py" \
      > "$ROOT/logs/socrates_full.log" 2>&1 &
    echo $! > "$ROOT/results/socrates_full.pid"
    echo "STARTED socrates pid=$(cat "$ROOT/results/socrates_full.pid")"
    ;;
  minitaur)
    # Need Psych-101-test data
    if [[ ! -f "$ROOT/data/Psych-101-test/prompts_testing_t1.jsonl" ]]; then
      mkdir -p "$ROOT/data/Psych-101-test"
      if command -v hf >/dev/null 2>&1; then
        hf buckets sync hf://buckets/shreyaspatel/Psych-101-test-bucket "$ROOT/data/Psych-101-test" || true
      fi
      if [[ ! -f "$ROOT/data/Psych-101-test/prompts_testing_t1.jsonl" ]]; then
        # fallback: expect uploaded from laptop
        echo "WAITING for Psych-101-test data at $ROOT/data/Psych-101-test/"
        exit 2
      fi
    fi
    # Patch ROOT paths in script expect /content/fm_baselines — symlink
    mkdir -p /content
    ln -sfn "$ROOT" /content/fm_baselines
    nohup env SMOKE_N=0 MAX_SEQ=4096 \
      python3 -u "$ROOT/scripts/colab_minitaur_psych101_nll.py" \
      > "$ROOT/logs/minitaur_full.log" 2>&1 &
    echo $! > "$ROOT/results/minitaur_full.pid"
    echo "STARTED minitaur pid=$(cat "$ROOT/results/minitaur_full.pid")"
    ;;
  befm)
    mkdir -p /content
    ln -sfn "$ROOT" /content/fm_baselines
    # Expect adapter + BehaviorBench already synced under $ROOT
    nohup env \
      python3 -u "$ROOT/scripts/colab_befm4b_serve_and_eval.py" \
      > "$ROOT/logs/befm_full.log" 2>&1 &
    echo $! > "$ROOT/results/befm_full.pid"
    echo "STARTED befm pid=$(cat "$ROOT/results/befm_full.pid")"
    ;;
  *)
    echo "unknown job $JOB"; exit 1
    ;;
esac
