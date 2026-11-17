#!/usr/bin/env bash
# Nightly own-IP jobs on two fleet slots (orchestrator 07:55Z / 08:15Z Nov 17), checked every 30 s for today's PT day:
#   - product sites: once raw/daily/<day>/today_0005.json lands and sites_0005.json is missing -> SITES_SLOT
#   - maker headers: once raw/ph_at_launch/<day>/makers_header.jsonl has rows not yet read      -> MAKERS_SLOT
# Each job pauses its slot's historical work only while it runs (ph_sites_resolve_run.sh).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
SITES_SLOT="${SITES_SLOT:-32}"
MAKERS_SLOT="${MAKERS_SLOT:-34}"
RAW="gs://${MVP_GCS_BUCKET}/usersim_sim/raw"
ART="$ROOT/results/ph_fleet_full/${PACE_FLEET_RUN_ID:-20261108t082000z}"
declare -A makers_tries=()
while true; do
  D=$(TZ=America/Los_Angeles date +%F)
  if gsutil -q stat "$RAW/daily/$D/today_0005.json" 2>/dev/null && ! gsutil -q stat "$RAW/daily/$D/sites_0005.json" 2>/dev/null; then
    echo "$(date -u +%FT%TZ) sites $D slot $SITES_SLOT" >>"$ART/sites_nightly.log"
    bash "$ROOT/scripts/vm/ph_sites_resolve_run.sh" "$SITES_SLOT" "$D" >>"$ART/sites_nightly.log" 2>&1 &
  fi
  if [[ "${makers_tries[$D]:-0}" -lt 3 ]] && gsutil -q cat "$RAW/ph_at_launch/$D/makers_header.jsonl" 2>/dev/null \
      | python3 -c 'import json,sys; sys.exit(0 if any(json.loads(l).get("status") != 200 for l in sys.stdin if l.strip()) else 1)'; then
    makers_tries[$D]=$(( ${makers_tries[$D]:-0} + 1 ))
    echo "$(date -u +%FT%TZ) makers $D slot $MAKERS_SLOT try ${makers_tries[$D]}" >>"$ART/makers_nightly.log"
    JOB_SCRIPT=ph_maker_headers.py bash "$ROOT/scripts/vm/ph_sites_resolve_run.sh" "$MAKERS_SLOT" "$D" >>"$ART/makers_nightly.log" 2>&1 &
  fi
  wait
  sleep 30
done
