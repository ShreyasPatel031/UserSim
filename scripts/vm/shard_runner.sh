#!/usr/bin/env bash
# Runs one bakeoff shard on a fleet VM, then reports to GCS and deletes the VM.
#
# Spot-safe resume: progress is checkpointed to GCS after every completed task.
# On start (or --relaunch after preemption) we restore that checkpoint before
# --resume, so only unfinished eval_indices re-run.
#
# Expected env: STAGE TAG SHARD_ID NUM_SHARDS MODEL WORKERS GCS_PREFIX
#               FAST ACTIONS_PER_STEP RESUME KEEP_VM MAX_ACTIONS EXTRA_ENV EVAL_INDICES
set -uo pipefail

cd "$HOME/usersim"

: "${STAGE:?}" "${TAG:?}" "${SHARD_ID:?}" "${NUM_SHARDS:?}" "${MODEL:?}"
: "${WORKERS:?}" "${GCS_PREFIX:?}"
FAST="${FAST:-0}"
ACTIONS_PER_STEP="${ACTIONS_PER_STEP:-3}"
RESUME="${RESUME:-1}"
KEEP_VM="${KEEP_VM:-0}"
# 0 = leave the harness default (MAX_ACTIONS in capability/__init__).
MAX_ACTIONS="${MAX_ACTIONS:-0}"
# Space-separated KEY=VALUE pairs so an experiment arm can set its own flags
# without this script needing to know about them.
EXTRA_ENV="${EXTRA_ENV:-}"
EVAL_INDICES="${EVAL_INDICES:-}"
PREFLIGHT="${PREFLIGHT:-0}"

SHARD_TAG="${TAG}_shard${SHARD_ID}"
MANIFEST="results/capability/${STAGE}_browser_use_${SHARD_TAG}.json"
LOG="$HOME/bakeoff_shard${SHARD_ID}.log"
DEST="${GCS_PREFIX}/${STAGE}/${TAG}"

set -a
# shellcheck disable=SC1091
source secrets/env
set +a
export BROWSER_USE_FAST="$FAST"
export BROWSER_USE_MAX_ACTIONS_PER_STEP="$ACTIONS_PER_STEP"
# Incremental checkpoints for Spot resume (see capability.gcs_checkpoint).
export CAPABILITY_GCS_CHECKPOINT="$DEST"
export CAPABILITY_SHARD_ID="$SHARD_ID"

resume_flag=()
[[ "$RESUME" == "1" ]] && resume_flag=(--resume)
budget_flag=()
[[ "$MAX_ACTIONS" != "0" ]] && budget_flag=(--max-actions "$MAX_ACTIONS")
preflight_flag=()
[[ "$PREFLIGHT" == "0" ]] && preflight_flag=(--no-preflight)

if [[ -n "$EXTRA_ENV" ]]; then
  for kv in $EXTRA_ENV; do export "${kv?}"; done
fi

eval_flag=()
[[ -n "$EVAL_INDICES" ]] && eval_flag=(--eval-indices "$EVAL_INDICES")

mkdir -p results/capability/traces

# Restore prior progress before bakeoff so --resume has something to skip.
echo "Restoring checkpoint from ${DEST} (if any)..."
gcloud storage cp "${DEST}/manifests/$(basename "$MANIFEST")" "$MANIFEST" --quiet 2>/dev/null \
  && echo "  restored $(basename "$MANIFEST")" \
  || echo "  no prior manifest"
gcloud storage rsync --recursive "${DEST}/traces/shard${SHARD_ID}" results/capability/traces --quiet 2>/dev/null \
  || true

PYTHONPATH=src .venv/bin/python -m capability.run_bakeoff \
  --stage "$STAGE" --harness browser_use --model "$MODEL" --workers "$WORKERS" \
  --num-shards "$NUM_SHARDS" --shard-id "$SHARD_ID" \
  --tag "$SHARD_TAG" "${budget_flag[@]}" "${eval_flag[@]}" "${resume_flag[@]}" \
  "${preflight_flag[@]}"
rc=$?
echo "BAKEOFF_EXIT=$rc"

# Judge creds are bundled on the VM, so re-score here rather than over SSH later.
PYTHONPATH=src .venv/bin/python -m capability.rejudge --manifest "$MANIFEST" || true

# Final sync (incremental checkpoints already ran per-task).
gcloud storage cp "$MANIFEST" "${DEST}/manifests/" --quiet || true
gcloud storage cp "$LOG" "${DEST}/logs/" --quiet || true
if [[ -d results/capability/traces ]]; then
  gcloud storage rsync --recursive results/capability/traces \
    "${DEST}/traces/shard${SHARD_ID}" --quiet || true
fi

marker="/tmp/shard${SHARD_ID}.done"
{
  echo "shard=$SHARD_ID"
  echo "exit=$rc"
  echo "finished=$(date -Is)"
} > "$marker"
gcloud storage cp "$marker" "${DEST}/_done/" --quiet || true

if [[ "$KEEP_VM" == "1" ]]; then
  echo "KEEP_VM=1, leaving instance up"
  exit "$rc"
fi

meta="http://metadata.google.internal/computeMetadata/v1/instance"
name=$(curl -sf -H 'Metadata-Flavor: Google' "$meta/name" || true)
zone=$(curl -sf -H 'Metadata-Flavor: Google' "$meta/zone" | awk -F/ '{print $NF}' || true)
if [[ -n "$name" && -n "$zone" ]]; then
  gcloud compute instances delete "$name" --zone="$zone" --quiet && exit "$rc"
fi
# Fall back to halting so we at least stop paying for CPU.
sudo poweroff
