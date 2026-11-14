#!/usr/bin/env bash
# 15m check-in: people/min, VM+proxy cost estimate, completeness sample, autoscale, Claude relay.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
export GCP_PROJECT PACE_ZONE MVP_GCS_BUCKET
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
export FLEET_ART="$ART" PACE_FLEET_RUN_ID="$RUN_ID" PACE_REPO_ROOT="$ROOT"
export AGENT_MSGS_PROJECT="${AGENT_MSGS_PROJECT:-${GCP_PROJECT:-}}"
[[ -n "${AGENT_MSGS_PROJECT}" ]] || { echo "set AGENT_MSGS_PROJECT or GCP_PROJECT for Pub/Sub relay" >&2; exit 1; }
INBOX="$ART/agent_inbox.jsonl"
export FLEET_MAX_VMS="${FLEET_MAX_VMS:-20}" FLEET_MIN_VMS="${FLEET_MIN_VMS:-8}"
PH_FLEET_STRATEGY="${PH_FLEET_STRATEGY:-$ROOT/scripts/vm/ph_strategies/fleet_iproyal.env}"
export PH_FLEET_STRATEGY
LOG="$ART/checkin.log"
HOURLY="${FLEET_HOURLY_USD:-0.06701}"

chmod +x "$ROOT/scripts/vm/ph_fleet_live_priority.sh" 2>/dev/null || true
if [[ -x "$ROOT/scripts/vm/ph_fleet_live_priority.sh" ]]; then
  bash "$ROOT/scripts/vm/ph_fleet_live_priority.sh" status >>"$LOG" 2>&1 || true
  # shellcheck source=/dev/null
  eval "$(bash "$ROOT/scripts/vm/ph_fleet_live_priority.sh" env 2>/dev/null)" || true
  if [[ "${PH_FLEET_LIVE_PRIORITY_HOLD:-0}" == "1" ]]; then
    echo "$(date -u +%FT%TZ) LIVE_PRIORITY_HOLD stale=${PH_FLEET_LIVE_STALE_FEEDS:-?} FLEET_MAX_VMS=${FLEET_MAX_VMS:-?}" >>"$LOG"
  fi
fi
if [[ -f "$ROOT/secrets/iproyal.env" && -x "$ROOT/scripts/vm/ph_iproyal_sync_pool.sh" ]]; then
  bash "$ROOT/scripts/vm/ph_iproyal_sync_pool.sh" >>"$LOG" 2>&1 || true
fi
if [[ -f "${PACE_IPROYAL_POOL:-$ROOT/secrets/iproyal.pool}" && -x "$ROOT/scripts/vm/ph_iproyal_ensure_slot_proxies.sh" ]]; then
  bash "$ROOT/scripts/vm/ph_iproyal_ensure_slot_proxies.sh" >>"$LOG" 2>&1 || true
fi

export FLEET_WINDOW_MIN="${FLEET_WINDOW_MIN:-15}"
measure="$(python3 "$ROOT/scripts/vm/ph_fleet_measure.py" 2>/dev/null)" || measure="{}"
chmod +x "$ROOT/scripts/vm/ph_fleet_fixes_audit.sh" "$ROOT/scripts/vm/ph_fleet_population_coord.sh" 2>/dev/null || true
# Never source fleet_optimize.env here (PH_BLOCK_NEW_PORT=1 breaks IPRoyal). Strategy = PH_FLEET_STRATEGY only.
source "$PH_FLEET_STRATEGY" 2>/dev/null || true
_act="$(echo "$measure" | python3 -c "import json,sys; m=json.load(sys.stdin); print(m.get('active_vms',0))" 2>/dev/null || echo 0)"
_ppm="$(echo "$measure" | python3 -c "import json,sys; m=json.load(sys.stdin); print(m.get('complete_ppm',m.get('realized_ppm',0)))" 2>/dev/null || echo 0)"
# Below target: audit-only — parallel rolls during recovery crater the 15m ppm window.
FLEET_TARGET_LO="${FLEET_TARGET_LO:-20}"
if python3 -c "exit(0 if float('${_ppm}' or 0) < float('${FLEET_TARGET_LO}') or int('${_act}' or 0) < 3 else 1)" 2>/dev/null; then
  export FLEET_FIXES_REPAIR=0
  fixes="$(bash "$ROOT/scripts/vm/ph_fleet_fixes_audit.sh" 2>/dev/null | tail -1)" || fixes="FIXES_AUDIT skipped (below target)"
  echo "$(date -u +%FT%TZ) FIXES_REPAIR_PAUSED ppm=${_ppm} active=${_act} lo=${FLEET_TARGET_LO}" >>"$LOG"
else
  fixes="$(bash "$ROOT/scripts/vm/ph_fleet_fixes_audit.sh" 2>/dev/null | tail -1)" || fixes="FIXES_AUDIT failed"
fi
echo "$(date -u +%FT%TZ) $fixes" >>"$LOG"
echo "$(date -u +%FT%TZ) measure=$measure" >>"$LOG"

n="$(echo "$measure" | python3 -c "import json,sys; print(json.load(sys.stdin).get('vms',0))" 2>/dev/null || echo 0)"
ppm="$(echo "$measure" | python3 -c "import json,sys; m=json.load(sys.stdin); print(m.get('complete_ppm',m.get('realized_ppm',0)))" 2>/dev/null || echo 0)"
attempt_ppm="$(echo "$measure" | python3 -c "import json,sys; print(json.load(sys.stdin).get('attempt_ppm',0))" 2>/dev/null || echo 0)"
rerun_ppm="$(echo "$measure" | python3 -c "import json,sys; print(json.load(sys.stdin).get('rerun_ppm',0))" 2>/dev/null || echo 0)"
vm_day="$(python3 -c "print(round(float($n)*float($HOURLY)*24,2))")"
vm_hr="$(python3 -c "print(round(float($n)*float($HOURLY),4))")"
eff="$(python3 -c "p=float('$ppm' or 0); c=float('$vm_hr' or 1); print(round(p/c,4) if c>0 else 0)")"
# Impulse proxy: ~$4/GB (list); sample last status mb from warm slots
proxy_gb=0
proxy_slots_sampled=0

# Sample completeness from 4 warm VMs via status tail coverage/header_pct
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
incomplete=0
complete=0
sampled=0
for slot in 4 13 16 19; do
  line="$(gcloud --account="$SA" compute ssh "feeder-fleet-${RUN_ID}-${slot}" --zone="$PACE_ZONE" --project="$GCP_PROJECT" \
    --tunnel-through-iap --quiet --ssh-flag=-o ConnectTimeout=8 </dev/null --command="python3 -c '
import json,glob,sys
best=None
for p in glob.glob(\"/opt/ph/reuse/status_*.jsonl\"):
  for ln in open(p):
    try: j=json.loads(ln)
    except Exception: continue
    if j.get(\"handle\") and j.get(\"coverage\"): best=j
if not best: sys.exit(0)
cov=best.get(\"coverage\") or {}
hp=best.get(\"header_pct\")
bad=False
for k,v in cov.items():
  if not isinstance(v,dict): continue
  if v.get(\"status\")==\"partial\": bad=True
  pct=v.get(\"pct\")
  if pct is not None and float(pct)<95 and v.get(\"status\")!=\"complete_not_visible\": bad=True
  if v.get(\"header\") and v.get(\"got\") is not None and v[\"header\"] and float(v[\"got\"])/max(1,float(v[\"header\"]))<0.95 and v.get(\"status\")!=\"complete_not_visible\": bad=True
print(\"incomplete\" if bad or (hp is not None and float(hp)<98) else \"complete\")
' 2>/dev/null" 2>/dev/null || true)"
  [[ -z "$line" ]] && continue
  sampled=$((sampled+1))
  [[ "$line" == incomplete* ]] && incomplete=$((incomplete+1)) || complete=$((complete+1))
  mb="$(gcloud --account="$SA" compute ssh "feeder-fleet-${RUN_ID}-${slot}" --zone="$PACE_ZONE" --project="$GCP_PROJECT" \
    --tunnel-through-iap --quiet --ssh-flag=-o ConnectTimeout=8 </dev/null --command="python3 -c '
import json,glob
best=0.0
for p in glob.glob(\"/opt/ph/reuse/status_*.jsonl\"):
  for ln in open(p):
    try: j=json.loads(ln)
    except Exception: continue
    if j.get(\"mb\"): best=float(j[\"mb\"])
print(best)
' 2>/dev/null" 2>/dev/null || true)"
  if [[ -n "$mb" ]] && python3 -c "float('$mb')>0" 2>/dev/null; then
    proxy_gb="$(python3 -c "print(round(float('$proxy_gb')+float('$mb')/1000,4))")"
    proxy_slots_sampled=$((proxy_slots_sampled+1))
  fi
done
proxy_day=""
if [[ "$proxy_slots_sampled" -gt 0 ]]; then
  proxy_day="$(python3 -c "gb=float('$proxy_gb'); rate=float('$ppm' or 0); print(round(gb*rate*60*24*4,2) if rate>0 else round(gb*4,2))")"
fi

chmod +x "$ROOT/scripts/vm/ph_fleet_utilization_recover.sh" "$ROOT/scripts/vm/ph_iproyal_refresh_slot.sh" 2>/dev/null || true
chmod +x "$ROOT/scripts/vm/ph_iproyal_block_rotate.sh" "$ROOT/scripts/vm/ph_iproyal_rotate_slot.sh" 2>/dev/null || true
if [[ "${PH_FLEET_LIVE_PRIORITY_HOLD:-0}" != "1" ]]; then
  bash "$ROOT/scripts/vm/ph_fleet_utilization_recover.sh" >>"$LOG" 2>&1 || true
  bash "$ROOT/scripts/vm/ph_iproyal_block_rotate.sh" >>"$LOG" 2>&1 || true
else
  echo "$(date -u +%FT%TZ) LIVE_PRIORITY skip utilization_recover block_rotate" >>"$LOG"
fi
chmod +x "$ROOT/scripts/vm/ph_fleet_cf_wall_recover.sh" 2>/dev/null || true
# Hung batches: limited kicks; CF block exit is port-swap via PH_BLOCK_NEW_PORT on supervisor.
export FLEET_CF_RECOVER_MAX_KICKS="${FLEET_CF_RECOVER_MAX_KICKS:-1}"
# Below target, never mass-kick (port-swap on supervisor handles CF; kicks were killing long whole pulls).
python3 -c "import sys; sys.exit(0 if float('${ppm}' or 0) < float('${FLEET_TARGET_LO:-20}') else 1)" 2>/dev/null && export FLEET_CF_RECOVER_MAX_KICKS=0
"$ROOT/scripts/vm/ph_fleet_cf_wall_recover.sh" >>"$LOG" 2>&1 || true
if [[ "${PH_FLEET_LIVE_PRIORITY_HOLD:-0}" != "1" ]]; then
  KEEPER_NUDGE_BUDGET="${KEEPER_NUDGE_BUDGET:-12}" bash "$ROOT/scripts/vm/ph_fleet_full_experiment.sh" keeper >>"$LOG" 2>&1 || true
else
  echo "$(date -u +%FT%TZ) LIVE_PRIORITY skip keeper" >>"$LOG"
fi
# Below target: still shed idle slots when yield collapsed (many VMs, ~0.3 ppm each).
FLEET_TARGET_LO="${FLEET_TARGET_LO:-20}"
export FLEET_AUTOSCALE_NO_SHED=1
python3 -c "
import json
m=json.load(open('$ART/fleet_measure.json'))
c=float(m.get('complete_ppm') or 0)
lo=float('${FLEET_TARGET_LO}')
ap=float(m.get('avg_ppm_productive') or 0)
nv=int(m.get('vms') or 0)
if c >= lo:
    raise SystemExit(0)
if ap < 0.75 and nv > 22:
    raise SystemExit(0)  # allow shed
raise SystemExit(1)
" 2>/dev/null && export FLEET_AUTOSCALE_NO_SHED=0 || true
export FLEET_TARGET_HI="${FLEET_TARGET_HI:-30}" FLEET_TARGET_MID="${FLEET_TARGET_MID:-25}"
"$ROOT/scripts/vm/ph_fleet_autoscale.sh" once >>"$LOG" 2>&1 || true

rerun_pct="$(python3 -c "a=float('$attempt_ppm' or 0) or 1; print(round(100*float('$rerun_ppm' or 0)/a,1))")"
eff_pop="$(python3 -c "a=float('$attempt_ppm' or 0) or 1; print(round(float('$ppm' or 0)/a,4))")"  # complete per attempt = Population-aligned efficiency
live_note=""
if [[ -f "$ART/live_feed_health.json" ]]; then
  live_note="$(python3 -c "import json; r=json.load(open('$ART/live_feed_health.json')); stale=[f['feed'] for f in r.get('feeds',[]) if f.get('stale')]; print('live_feeds_ok='+('yes' if not r.get('any_stale') else 'NO stale='+','.join(stale)))" 2>/dev/null || true)"
fi
relay_msg="Fleet check-in run=$RUN_ID complete_ppm=$ppm attempt_ppm=$attempt_ppm rerun_ppm=$rerun_ppm rerun_pct=${rerun_pct}% complete_per_attempt=$eff_pop vms=$n vm~\$$vm_day/day eff_complete_over_compute=${eff}. ${live_note} POLICY: live 15m feeds win — any stale posts_ts/snapshots/api_comments => historical throttle (IPROYAL_DAILY_IPS=${IPROYAL_DAILY_IPS:-2} reserved). OPS: no pause-on-block from agents; sustained block => rotate Finland dedicated IP (slot1 included); new IP on keeper recreate. GOAL lastweek 100%. PH_RR_FILES=0945Z_lastweek_votes(953),vmgate,follow,signedin,overnight. full18f uYYdW17hoPBJjpMGoR7lKw== save=_pacetest/shared."
[[ -n "$proxy_day" ]] && relay_msg+=" proxy_est~\$$proxy_day/day (Impulse ~\$4/GB, sampled ${proxy_gb}GB recent pulls)"
relay_msg+=". VM smoke sample $sampled rows: complete=$complete incomplete=$incomplete (legacy header/tab; Population whole() is authority). RR_ONLY queue rerun_whole_20261110T0230Z_lastweek_priority.txt (no port rotate)."
if [[ "$incomplete" -gt 0 ]]; then
  relay_msg+=" INCOMPLETE_SAVES in sample — Population full audit required; PH_REQUIRE_FULL_SAVE blocks new bad uploads."
fi
relay_msg+=" zero_incomplete=UNVERIFIED. Request Population repair_list recheck loop."
"$ROOT/scripts/vm/ph_fleet_agent_relay.sh" population fleet-cursor "$relay_msg" >>"$LOG" 2>&1 || true
short_all="fleet-cursor check-in run=$RUN_ID complete_ppm=$ppm vms=$n. status=gs://${MVP_GCS_BUCKET}/usersim_sim/mailbox/from_cursor/status.json (15m). Reply mailbox=usersim_sim/mailbox/from_cursor/."
"$ROOT/scripts/vm/ph_fleet_agent_relay.sh" all fleet-cursor "$short_all" >>"$LOG" 2>&1 || true
chmod +x "$ROOT/scripts/vm/ph_fleet_cursor_mailbox_status.sh" 2>/dev/null || true
"$ROOT/scripts/vm/ph_fleet_cursor_mailbox_status.sh" >>"$LOG" 2>&1 || true
chmod +x "$ROOT/scripts/vm/ph_fleet_cursor_publish_bc.sh" 2>/dev/null || true
"$ROOT/scripts/vm/ph_fleet_cursor_publish_bc.sh" >>"$LOG" 2>&1 || true
mkdir -p "$ART/agent_inbox"
AGENT_INBOX_JSONL="$ART/agent_inbox/fleet-cursor.jsonl" AGENT_MSGS_SUB=fleet-cursor \
  bash "$ROOT/scripts/vm/ph_fleet_agent_inbox.sh" 15 checkin >>"$LOG" 2>&1 || true
# Population inbox: queue/audit/quality only. Stop/start/VM count/GO = operator only (not Population).
if [[ -f "$ART/agent_inbox/fleet-cursor.jsonl" ]]; then
  python3 -c "
import json
from pathlib import Path
p=Path('$ART/agent_inbox/fleet-cursor.jsonl')
for ln in p.read_text().splitlines()[-20:]:
  try: j=json.loads(ln)
  except: continue
  if (j.get('from') or '').startswith('population') and 'repair_list' in (j.get('data') or ''):
    print('POPULATION_REPAIR_LIST_SEEN', j.get('utc'))
" >>"$LOG" 2>/dev/null || true
fi

# Single babysit path also refreshes fleet-dashboard/ (measure at top) and keeps local static server up.
if ! pgrep -f '[h]ttp.server 8765' >/dev/null; then
  DASH="$ROOT/fleet-dashboard"
  SESSION_NAME="ph-fleet-dashboard"
  tmux -f /exec-daemon/tmux.portal.conf has-session -t "=$SESSION_NAME" 2>/dev/null \
    || tmux -f /exec-daemon/tmux.portal.conf new-session -d -s "$SESSION_NAME" -c "$DASH"
  tmux -f /exec-daemon/tmux.portal.conf send-keys -t "$SESSION_NAME:0.0" \
    "cd $DASH && exec python3 -m http.server 8765 --bind 0.0.0.0" C-m
fi

echo "CHECKIN complete_ppm=$ppm attempt_ppm=$attempt_ppm rerun_ppm=$rerun_ppm vms=$n vm~\$$vm_day/day eff=$eff pop_audit=incomplete_not_zero"
