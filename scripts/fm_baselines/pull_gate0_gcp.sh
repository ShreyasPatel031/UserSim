#!/bin/bash
set -euo pipefail
ZONE=us-central1-b
REPO=/Users/shreyaspatel/Desktop/Code/UserSim
pull_one() {
  local name="$1" remote="$2" localdir="$3"
  mkdir -p "$localdir"
  gcloud compute scp --zone=$ZONE --tunnel-through-iap \
    "$name:$remote" "$localdir/" 2>/dev/null || true
}
while true; do
  echo "=== $(date -u +%H:%M:%S) pull ==="
  # Socrates
  gcloud compute ssh fm-gate0-socrates --zone=$ZONE --tunnel-through-iap --command='
    pid=$(cat /content/fm_baselines/results/socrates_full.pid 2>/dev/null || echo none)
    alive=no; [[ -d /proc/$pid ]] && alive=yes
    preds=$(wc -l </content/fm_baselines/results/socrates/predictions.jsonl 2>/dev/null || echo 0)
    echo "socrates pid=$pid alive=$alive preds=$preds"
    tail -n 3 /content/fm_baselines/logs/socrates_full.log 2>/dev/null || true
  ' 2>/dev/null | rg -v 'WARNING|NumPy|known hosts|Permanently|To increase' || echo 'socrates ssh fail'
  pull_one fm-gate0-socrates /content/fm_baselines/results/socrates/SUMMARY.json "$REPO/results/fm_baselines/socrates"
  pull_one fm-gate0-socrates /content/fm_baselines/results/socrates/PARTIAL.*.json "$REPO/results/fm_baselines/socrates" || true
  pull_one fm-gate0-socrates /content/fm_baselines/results/socrates/predictions.jsonl "$REPO/results/fm_baselines/socrates"

  # Minitaur
  gcloud compute ssh fm-gate0-minitaur --zone=$ZONE --tunnel-through-iap --command='
    pid=$(cat /content/fm_baselines/results/minitaur_full.pid 2>/dev/null || echo none)
    alive=no; [[ -d /proc/$pid ]] && alive=yes
    echo "minitaur pid=$pid alive=$alive"
    cat /content/fm_baselines/results/minitaur/PROGRESS.json 2>/dev/null || true
    tail -n 3 /content/fm_baselines/logs/minitaur_full.log 2>/dev/null || true
  ' 2>/dev/null | rg -v 'WARNING|NumPy|known hosts|Permanently|To increase' || echo 'minitaur ssh fail'
  pull_one fm-gate0-minitaur /content/fm_baselines/results/minitaur/SUMMARY.json "$REPO/results/fm_baselines/minitaur"
  pull_one fm-gate0-minitaur /content/fm_baselines/results/minitaur/PROGRESS.json "$REPO/results/fm_baselines/minitaur"
  pull_one fm-gate0-minitaur /content/fm_baselines/results/minitaur/PARTIAL.*.json "$REPO/results/fm_baselines/minitaur" || true

  # BeFM if present
  if gcloud compute instances describe fm-gate0-befm --zone=$ZONE >/dev/null 2>&1; then
    gcloud compute ssh fm-gate0-befm --zone=$ZONE --tunnel-through-iap --command='
      pid=$(cat /content/fm_baselines/results/befm_full.pid 2>/dev/null || echo none)
      alive=no; [[ -d /proc/$pid ]] && alive=yes
      echo "befm pid=$pid alive=$alive"
      tail -n 3 /content/fm_baselines/logs/befm_full.log 2>/dev/null || true
    ' 2>/dev/null | rg -v 'WARNING|NumPy|known hosts|Permanently|To increase' || true
    pull_one fm-gate0-befm /content/fm_baselines/results/befm4b/SUMMARY.json "$REPO/results/fm_baselines/befm4b"
  fi

  python3 "$REPO/scripts/gates/verify.py" --gate 0 || true
  sleep 300
done
