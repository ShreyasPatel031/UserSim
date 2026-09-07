#!/bin/bash
# Keep fm-floor-qwen-l4 up and the Be.FM floor job running until SUMMARY.complete.
set -u
PROJECT="${PROJECT:?set PROJECT to the GCP project id}"
ZONE="${ZONE:?set ZONE to the VM zone}"
VM="${VM:-fm-floor-qwen-l4}"
ROOT="${USERSIM_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOG="${LOG:-$ROOT/results/fm_baselines/qwen_befm_watchdog.log}"
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
alive=False
for name in Path("/proc").iterdir():
    if not name.name.isdigit():
        continue
    try:
        cmd=open(name/"cmdline","rb").read().decode("utf-8","replace")
    except Exception:
        continue
    if "colab_qwen3_8b_floor_befm.py" in cmd or "vllm.entrypoints.openai" in cmd:
        alive=True
        break
prog=root/"PROGRESS.json"
n=0
cur=""
eng=""
if prog.exists():
    p=json.loads(prog.read_text())
    n=p.get("n_done",0)
    cur=(p.get("current") or [""])[0]
    eng=p.get("engine","")
print(("ALIVE" if alive else "DEAD") + f" done={n}/39 current={cur} engine={eng}")
if not alive:
    raise SystemExit(2)
PY
' 2>>"$LOG") || true

  if echo "$OUT" | grep -q DONE; then
    log "COMPLETE -> stop VM + drop spot-watch"
    gcloud compute instances remove-labels "$VM" --zone="$ZONE" --project="$PROJECT" --labels=usersim-spot-watch >>"$LOG" 2>&1 || true
    gcloud compute instances stop "$VM" --zone="$ZONE" --project="$PROJECT" >>"$LOG" 2>&1 || true
    exit 0
  fi

  if echo "$OUT" | grep -q DEAD; then
    log "job dead ($OUT) -> systemd restart"
    gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap \
      --command='sudo systemctl restart usersim-floor-befm.service || bash /opt/usersim_fm/scripts/run_qwen_befm_full.sh' >>"$LOG" 2>&1 || true
  else
    log "ok $OUT"
  fi
  sleep 120
done
