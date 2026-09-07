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
    sleep 50
    continue
  fi

  OUT=$(gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --command='
python3 - <<"PY"
import json
from pathlib import Path
root=Path("/opt/usersim_fm/results/qwen3_8b_base_befm")
s=root/"SUMMARY.json"
if s.exists():
    d=json.loads(s.read_text())
    if d.get("complete"):
        print("DONE")
        raise SystemExit(0)
active=False
for name in ("usersim-floor-befm.service",):
    p=Path("/proc/1")
# systemd active?
import subprocess
st=subprocess.run(["systemctl","is-active","usersim-floor-befm.service"], capture_output=True, text=True)
alive = st.stdout.strip()=="active"
prog=root/"PROGRESS.json"
n=0
cur=""
eng=""
if prog.exists():
    p=json.loads(prog.read_text())
    n=p.get("n_done",0)
    cur=(p.get("current") or [""])[0] if p.get("current") else ""
    eng=p.get("engine","")
print(("ALIVE" if alive else "DEAD") + f" done={n}/39 current={cur} engine={eng}")
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
    log "job dead ($OUT) -> systemd restart"
    gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap \
      --command='sudo systemctl restart usersim-floor-befm.service' >>"$LOG" 2>&1 || true
  else
    log "ok $OUT"
  fi
  sleep 180
done
