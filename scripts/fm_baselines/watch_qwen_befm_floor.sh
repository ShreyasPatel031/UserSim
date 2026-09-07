#!/bin/bash
# Keep fm-floor-qwen-l4 alive until Be.FM floor SUMMARY is complete.
set -u
PROJECT=project-amer-scs-sandbox
ZONE=us-central1-a
VM=fm-floor-qwen-l4
LOG=/Users/shreyaspatel/Desktop/Code/UserSim/results/fm_baselines/qwen_befm_watchdog.log
mkdir -p "$(dirname "$LOG")"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

while true; do
  STATUS=$(gcloud compute instances describe "$VM" --zone="$ZONE" --project="$PROJECT" --format='value(status)' 2>/dev/null || echo UNKNOWN)
  if [[ "$STATUS" != "RUNNING" ]]; then
    log "VM status=$STATUS -> start"
    gcloud compute instances start "$VM" --zone="$ZONE" --project="$PROJECT" >>"$LOG" 2>&1 || true
    sleep 45
    continue
  fi

  # SSH: if SUMMARY complete, stop and exit
  OUT=$(gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --command='
python3 - <<"PY"
import json, os
from pathlib import Path
root=Path("/opt/usersim_fm/results/qwen3_8b_base_befm")
s=root/"SUMMARY.json"
if s.exists():
  d=json.loads(s.read_text())
  if d.get("complete"):
    print("DONE")
    raise SystemExit(0)
pid_p=Path("/opt/usersim_fm/results/qwen_befm_full.pid")
alive=False
if pid_p.exists():
  pid=pid_p.read_text().strip()
  alive=Path(f"/proc/{pid}").exists()
prog=root/"PROGRESS.json"
n=0
cur=""
if prog.exists():
  p=json.loads(prog.read_text())
  n=p.get("n_done",0)
  cur=(p.get("current") or [""])[0]
print(("ALIVE" if alive else "DEAD") + f" done={n}/39 current={cur}")
if not alive:
  raise SystemExit(2)
PY
' 2>>"$LOG") || true

  if echo "$OUT" | grep -q DONE; then
    log "COMPLETE -> stopping VM"
    gcloud compute instances stop "$VM" --zone="$ZONE" --project="$PROJECT" >>"$LOG" 2>&1 || true
    exit 0
  fi

  if echo "$OUT" | grep -q DEAD; then
    log "job dead ($OUT) -> relaunch"
    gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap \
      --command='bash /opt/usersim_fm/scripts/run_qwen_befm_full.sh' >>"$LOG" 2>&1 || true
  else
    log "ok $OUT"
  fi
  sleep 180
done
