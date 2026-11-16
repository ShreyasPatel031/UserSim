#!/usr/bin/env bash
# Orchestrator clean restart: list refill + audited full-only overlay roll + phsuper on existing IPs (no proxy rotate).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PACE_ENV_FILE="${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export PACE_FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
# shellcheck source=/dev/null
source "$PACE_ENV_FILE"
RUN_ID="${PACE_FLEET_RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
QUEUE="${FLEET_COMPLETION_QUEUE:-usersim_sim/raw/_cursor/completion_queue_20261115T1100Z.txt}"
export FLEET_HOLD_UNHANG=1
export FLEET_WAKEUP_MAX=12
export PH_FLEET_STRATEGY_ENV="${PH_FLEET_STRATEGY_ENV:-$ROOT/scripts/vm/ph_strategies/fleet_optimize.env}"
# Seeded pdeep_list is only used when RR_ONLY is off.
export PH_FLEET_COMPLETION_DRAIN="${PH_FLEET_COMPLETION_DRAIN:-1}"
echo "=== orch_clean_restart run=$RUN_ID utc=$(date -u +%FT%TZ)"
echo "=== seed pdeep_list queue=$QUEUE"
bash "$ROOT/scripts/vm/ph_fleet_seed_completion_queue.sh" "$QUEUE" || {
  echo "WARN seed failed — continuing with existing per-VM pdeep_list"
}
echo "=== roll patches (pdeep GO pinned; PH_SAVE_B via fleet_optimize.env _pacetest/shared)"
bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh"
echo "=== fixes audit (full-only probes)"
FLEET_FIXES_REPAIR=1 bash "$ROOT/scripts/vm/ph_fleet_fixes_audit.sh" | tee -a "$ART/orch_clean_restart.log"
python3 "$ROOT/scripts/vm/ph_fleet_measure.py"
echo "=== orch_clean_restart done"