#!/usr/bin/env bash
# Scale fleet 1:1 with IPRoyal pool (Spain slot 1 + dedicated ISPs), L3_mid, same-IP ISP strategy.
#   PACE_IPROYAL_FLEET_SLOTS=20 ./scripts/vm/ph_fleet_iproyal_optimize.sh
#   ./scripts/vm/ph_fleet_iproyal_optimize.sh deploy   # sync pool + scale + bind + roll
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
export PATH="/home/ubuntu/google-cloud-sdk/bin:${PATH:-}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt" 2>/dev/null)}"
RUN_ID="${RUN_ID,,}"
export PACE_FLEET_RUN_ID="$RUN_ID"
POOL="${PACE_IPROYAL_POOL:-$ROOT/secrets/iproyal.pool}"
bash "$ROOT/scripts/vm/ph_iproyal_sync_pool.sh"
N="$(grep -v '^[[:space:]]*#' "$POOL" | grep -v '^[[:space:]]*$' | wc -l)"
N="${IPROYAL_FLEET_N:-$N}"
WANT="${FLEET_MAX_VMS:-20}"
N=$(( N < WANT ? N : WANT ))
export IPROYAL_FLEET_N="$N" IPROYAL_FLEET_LEVEL="${IPROYAL_FLEET_LEVEL:-L3_mid}"
export FLEET_MAX_VMS="$WANT" FLEET_MIN_VMS="${FLEET_MIN_VMS:-8}" FLEET_TARGET_LO="${FLEET_TARGET_LO:-20}" FLEET_TARGET_HI="${FLEET_TARGET_HI:-30}"
export PH_FLEET_STRATEGY="$ROOT/scripts/vm/ph_strategies/fleet_iproyal.env"
echo "iproyal optimize: pool_lines=$N deploy_slots=$N max_vms=$WANT run=$RUN_ID level=$IPROYAL_FLEET_LEVEL"
bash "$ROOT/scripts/vm/ph_iproyal_deploy_fleet.sh"
MSG="POPULATION_COORD IPRoyal optimize $(date -u +%FT%TZ): scaled run=$RUN_ID to $N VMs (max $WANT). Finland-only pool (Spain retired on slot1). Rotate dedicated IP on block + VM recreate. L3_mid+fleet_iproyal. Goal 20 complete/min. zero_incomplete=UNVERIFIED."
bash "$ROOT/scripts/vm/ph_fleet_agent_relay.sh" population fleet-cursor "$MSG"
bash "$ROOT/scripts/vm/ph_fleet_agent_relay.sh" all fleet-cursor "fleet-cursor IPRoyal fleet optimize: $N feeders live, $WANT cap when pool hits 20 lines. Mailbox status.json updated each 15m."
