#!/usr/bin/env bash
# Start dedicated repullupvotes workers (orchestrator daily upvote_refresh).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export PACE_FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${PACE_FLEET_RUN_ID,,}"
export UPVOTE_SLOTS="${UPVOTE_SLOTS:-9 27 38}"
START_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
GO_TOKEN="${PH_GO_UPVOTE:-repullupvotes:fleet-upvote-${RUN_ID}-$(date -u +%Y%m%dT%H%MZ)}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
mkdir -p "$ART"
echo "$GO_TOKEN" >"$ART/upvote_go.token"
export PH_FLEET_STRATEGY_ENV="${PH_FLEET_STRATEGY_ENV:-$ROOT/scripts/vm/ph_strategies/fleet_upvote_refresh.env}"
export PH_GO_MODE="$GO_TOKEN"
export ONLY_SLOTS="$UPVOTE_SLOTS"
export PRESERVE_QUEUE_CACHE=1
bash "$ROOT/scripts/vm/ph_fleet_seed_upvote_refresh.sh" "${REFRESH_GCS:-usersim_sim/raw/_cursor/refresh_upvotes_20261112T2300Z.txt}"
bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh"
echo "UPVOTE_REFRESH start_utc=$START_UTC go=$GO_TOKEN slots=$UPVOTE_SLOTS"