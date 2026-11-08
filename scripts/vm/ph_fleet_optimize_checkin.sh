#!/usr/bin/env bash
# 15m check-in: people/min, VM+proxy cost estimate, completeness sample, autoscale, Claude relay.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
export GCP_PROJECT PACE_ZONE MVP_GCS_BUCKET
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
export FLEET_ART="$ART" PACE_FLEET_RUN_ID="$RUN_ID"
export AGENT_MSGS_PROJECT="${AGENT_MSGS_PROJECT:-${GCP_PROJECT:-}}"
[[ -n "${AGENT_MSGS_PROJECT}" ]] || { echo "set AGENT_MSGS_PROJECT or GCP_PROJECT for Pub/Sub relay" >&2; exit 1; }
INBOX="$ART/agent_inbox.jsonl"
export FLEET_MAX_VMS="${FLEET_MAX_VMS:-30}" PH_FLEET_STRATEGY="$ROOT/scripts/vm/ph_strategies/fleet_optimize.env"
LOG="$ART/checkin.log"
HOURLY="${FLEET_HOURLY_USD:-0.06701}"

measure="$(python3 "$ROOT/scripts/vm/ph_fleet_measure.py" 2>/dev/null)" || measure="{}"
echo "$(date -u +%FT%TZ) measure=$measure" >>"$LOG"

n="$(echo "$measure" | python3 -c "import json,sys; print(json.load(sys.stdin).get('vms',0))" 2>/dev/null || echo 0)"
ppm="$(echo "$measure" | python3 -c "import json,sys; print(json.load(sys.stdin).get('realized_ppm',0))" 2>/dev/null || echo 0)"
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

"$ROOT/scripts/vm/ph_fleet_autoscale.sh" once >>"$LOG" 2>&1 || true

relay_msg="Fleet check-in run=$RUN_ID realized_ppm=$ppm vms=$n vm~\$$vm_day/day efficiency=${eff} people/min per \$/hr_vm"
[[ -n "$proxy_day" ]] && relay_msg+=" proxy_est~\$$proxy_day/day (Impulse ~\$4/GB, sampled ${proxy_gb}GB recent pulls)"
relay_msg+=". Sample completeness $sampled pulls: complete=$complete incomplete=$incomplete (gate: PH_REQUIRE_FULL_SAVE=1 header>=98 tab>=95)."
if [[ "$incomplete" -gt 0 ]]; then
  relay_msg+=" INCOMPLETE_SAVES detected on fleet — verify orchestrator agrees before counting saves; rolling patch_require_full_save blocks gs upload."
fi
relay_msg+=" Ask orchestrator: confirm full18d pkg MD5 in COMMON_META + validate N saved in gs:// vs status incomplete_skip_upload events."
"$ROOT/scripts/vm/ph_fleet_agent_relay.sh" orchestrator fleet-cursor "$relay_msg" >>"$LOG" 2>&1 || true
# Pull any orchestrator / grok replies for fleet-cursor (no ack until AUTO_ACK=1).
if out="$("$ROOT/scripts/vm/ph_fleet_agent_inbox.sh" 3 2>/dev/null)"; then
  echo "$out" | python3 -c "
import json,sys
from datetime import datetime,timezone
raw=sys.stdin.read().strip()
if not raw: raise SystemExit
rows=json.loads(raw) if raw.startswith('[') else [json.loads(raw)]
for r in rows:
  m=r.get('message',{}) or {}
  attrs=dict((a.get('key'),a.get('value')) for a in m.get('attributes',[]) or [])
  line=json.dumps({'utc':datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),'from':attrs.get('from'),'to':attrs.get('to'),'data':m.get('data','')[:4000]})
  print(line)
" >>"$INBOX" 2>/dev/null || true
fi

echo "CHECKIN ppm=$ppm vms=$n vm~\$$vm_day/day eff=$eff complete=$complete incomplete=$incomplete sampled=$sampled"
