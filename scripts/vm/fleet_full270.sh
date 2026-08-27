#!/usr/bin/env bash
# Full270 matched-triplet fleet: 6 personas × 5 journeys × 3 seeds × 3 platforms = 270.
#
# Equal concurrency per platform (like full80 wall-clock ≈ longest task):
#   Default (post-audit): 12 Spot VMs × 4 workers × 3 platforms = 36 VMs
#   90 tasks/platform ÷ 12 shards ≈ 7–8 tasks/VM → ~2 waves with WORKERS=4
#   (WORKERS=8 overloaded Chromium/SPA loads → many 0-action harness timeouts.)
#
# Matched blocks (persona×journey×seed) are identical prompts on Bland/Vapi/Retell.
# Journeys 2–5 start from an existing baseline agent.
#
# Spot failures: --relaunch restores GCS checkpoints and resumes unfinished shards;
# KEEP_VM=0 deletes each VM after a complete shard (exit=0 + manifest + expected runs).
#
# Reserve ~30 sessions outside this set for invalid replacements / robustness —
# do not casually expand the primary 270 mid-run.
#
# Usage:
#   GEMINI_MODEL=gemini-2.5-flash FLEET_TAG=full270_flash_m40 ./scripts/vm/fleet_full270.sh
#   ./scripts/vm/fleet_full270.sh --status
#   ./scripts/vm/fleet_full270.sh --relaunch
#   ./scripts/vm/fleet_full270.sh --pull
#   ./scripts/vm/fleet_full270.sh --down
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

ACTION="${1:-}"
PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
MODEL="${GEMINI_MODEL:-gemini-2.5-flash}"
TAG="${FLEET_TAG:-full270_flash_m40}"
WORKERS="${WORKERS:-4}"
MACHINE="${GCP_MACHINE:-e2-standard-8}"
NUM_SHARDS_PER_PLATFORM="${NUM_SHARDS_PER_PLATFORM:-12}"
MAX_ACTIONS="${MAX_ACTIONS:-40}"
GCS_PREFIX="${GCS_PREFIX:-gs://usersim-bakeoff-347838016394}"
DEPLOY_PARALLEL="${DEPLOY_PARALLEL:-12}"
KEEP_VM="${KEEP_VM:-0}"
RESUME="${RESUME:-1}"
PLATS=(bland vapi retell)

for f in secrets/env secrets/vertex_adc.json \
         secrets/voice_ai_sessions/bland.json \
         secrets/voice_ai_sessions/vapi.json \
         secrets/voice_ai_sessions/retell.json; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: missing $f"
    exit 1
  fi
done

# Refresh short-lived Vapi WorkOS JWTs before packaging secrets onto VMs.
# Skip for status/pull/down/merge — only when we may create/relaunch shards.
if [[ -z "$ACTION" || "$ACTION" == "--relaunch" ]]; then
  echo "Refreshing Vapi WorkOS access tokens…"
  PYTHONPATH=src python3 - <<'PY'
from capability.voice_ai_dashboards import refresh_vapi_workos_session, write_sanitized_session
import json
print(json.dumps(refresh_vapi_workos_session(), indent=2))
for k in ("bland", "vapi", "retell"):
    write_sanitized_session(k)
print("sanitized sessions ok")
PY
fi

# Sanity: 270 cells
PYTHONPATH=src python3 - <<'PY'
from capability.voice_ai_full270 import full270_summary
s = full270_summary()
assert s["n"] == 270, s
assert s["per_platform"]["bland"] == 90
print("full270 ok:", s)
PY

run_platform_fleet() {
  local plat="$1"
  local cmd_args=("${@:2}")
  STAGE="product_full270_${plat}" \
  FLEET_PREFIX="usersim-bu-f270-${plat}" \
  FLEET_TAG="$TAG" \
  NUM_SHARDS="$NUM_SHARDS_PER_PLATFORM" \
  WORKERS="$WORKERS" \
  GCP_MACHINE="$MACHINE" \
  GCP_PROJECT="$PROJECT" \
  GEMINI_MODEL="$MODEL" \
  MAX_ACTIONS="$MAX_ACTIONS" \
  GCS_PREFIX="$GCS_PREFIX" \
  DEPLOY_PARALLEL="$DEPLOY_PARALLEL" \
  KEEP_VM="$KEEP_VM" \
  RESUME="$RESUME" \
  bash "$ROOT/scripts/vm/fleet_bakeoff.sh" "${cmd_args[@]}"
}

case "$ACTION" in
  --status)
    for plat in "${PLATS[@]}"; do
      echo "======== ${plat} ========"
      run_platform_fleet "$plat" --status || true
    done
    ;;
  --relaunch)
    for plat in "${PLATS[@]}"; do
      echo "======== relaunch ${plat} ========"
      run_platform_fleet "$plat" --relaunch
    done
    ;;
  --pull)
    for plat in "${PLATS[@]}"; do
      echo "======== pull ${plat} ========"
      run_platform_fleet "$plat" --pull || true
    done
    PYTHONPATH=src "${ROOT}/.venv/bin/python" - <<PY
import json
from pathlib import Path
from capability.metrics import sort_runs, summarize
out = Path("results/capability")
runs = []
for plat in ("bland", "vapi", "retell"):
    for p in sorted(out.glob(f"product_full270_{plat}_browser_use_${TAG}_shard*.json")):
        runs.extend(json.loads(p.read_text()).get("runs") or [])
merged = out / f"product_full270_browser_use_${TAG}.json"
base = {"stage": "product_full270", "harness": "browser_use", "model": "${MODEL}", "tag": "${TAG}"}
base.update(summarize(runs))
base["runs"] = sort_runs(runs)
merged.write_text(json.dumps(base, indent=2, default=str))
print(f"Merged {len(runs)} runs -> {merged.name}")
print(summarize(runs))
PY
    ;;
  --down)
    for plat in "${PLATS[@]}"; do
      echo "======== down ${plat} ========"
      run_platform_fleet "$plat" --down || true
    done
    ;;
  --merge)
    STAGE=product_full270 FLEET_TAG="$TAG" bash "$ROOT/scripts/vm/fleet_bakeoff.sh" --merge || true
    "$0" --pull
    ;;
  ""|--launch)
    echo "==> Launching full270: 3 platforms × ${NUM_SHARDS_PER_PLATFORM} VMs × ${WORKERS} workers"
    echo "    model=${MODEL} max_actions=${MAX_ACTIONS} tag=${TAG} machine=${MACHINE}"
    # Launch platforms sequentially for create, but each fleet deploys shards in parallel.
    # Overlap platform deploys: start all three create+deploy pipelines in background.
    pids=()
    for plat in "${PLATS[@]}"; do
      echo "==> Starting fleet for ${plat}"
      (
        run_platform_fleet "$plat"
      ) > "/tmp/full270_${plat}_launch.log" 2>&1 &
      pids+=($!)
    done
    fail=0
    for i in "${!pids[@]}"; do
      if ! wait "${pids[$i]}"; then
        echo "ERROR: fleet ${PLATS[$i]} failed — see /tmp/full270_${PLATS[$i]}_launch.log"
        fail=1
      else
        echo "OK: fleet ${PLATS[$i]} deployed"
      fi
    done
    if [[ "$fail" -ne 0 ]]; then
      exit 1
    fi
    echo "==> All 36 shards deploying. Monitor:"
    echo "    ./scripts/vm/fleet_full270.sh --status"
    echo "    ./scripts/vm/fleet_full270.sh --relaunch   # after spot preemptions"
    echo "    ./scripts/vm/fleet_full270.sh --pull"
    ;;
  *)
    echo "Usage: $0 [--launch|--status|--relaunch|--pull|--down|--merge]"
    exit 1
    ;;
esac
