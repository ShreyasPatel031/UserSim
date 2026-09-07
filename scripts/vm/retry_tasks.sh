#!/usr/bin/env bash
# Re-run specific eval_indices with maximum wall-clock parallelism.
#
# Default: 1 task per VM (NUM_SHARDS = number of indices) so all tasks start at once.
# For 8 tasks this is 8× e2-standard-2 Spot VMs → wall time ≈ slowest single task.
#
# Usage:
#   EVAL_INDICES='2,3,6,8,10,12,15,21' ./scripts/vm/retry_tasks.sh
#   EVAL_INDICES='2,3,6,8' BROWSER_USE_ARM=1 ./scripts/vm/retry_tasks.sh
#
# Pull when done:
#   STAGE=retry FLEET_TAG=<tag> ./scripts/vm/fleet_bakeoff.sh --pull
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

EVAL_INDICES="${EVAL_INDICES:?set EVAL_INDICES=2,3,6,...}"
ARM="${BROWSER_USE_ARM:-1}"
MAX_ACTIONS="${MAX_ACTIONS:-45}"
WORKERS="${WORKERS:-1}"
FAST="${FAST:-0}"

# One VM per task unless caller overrides.
N=$(echo "$EVAL_INDICES" | tr ',' '\n' | grep -c .)
NUM_SHARDS="${NUM_SHARDS:-$N}"
TAG="${FLEET_TAG:-retry_arm${ARM}_m${MAX_ACTIONS}_n${N}}"

export STAGE=retry
export NUM_SHARDS
export WORKERS
export MAX_ACTIONS
export EVAL_INDICES
export FLEET_TAG="$TAG"
export FLEET_PREFIX="${FLEET_PREFIX:-usersim-bu-retry}"
export EXTRA_ENV="BROWSER_USE_ARM=${ARM} BROWSER_USE_FAST=${FAST}"
export KEEP_VM=0

echo "==> retry_tasks: ${N} indices, ${NUM_SHARDS} VMs, workers=${WORKERS}, budget=${MAX_ACTIONS}, arm=${ARM}"
echo "    indices: ${EVAL_INDICES}"
echo "    tag:     ${TAG}"

exec "$ROOT/scripts/vm/fleet_bakeoff.sh"
