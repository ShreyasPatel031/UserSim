#!/usr/bin/env bash
# Runs one bakeoff shard on a fleet VM, then reports to GCS and deletes the VM.
#
# The VM is the only thing that knows when it is finished, so it does the whole
# tail itself: rejudge -> upload -> self-delete. Nothing on the operator side
# needs to poll over SSH, which is what used to make status checks take minutes.
#
# Expected env: STAGE TAG SHARD_ID NUM_SHARDS MODEL WORKERS GCS_PREFIX
#               FAST ACTIONS_PER_STEP RESUME KEEP_VM MAX_ACTIONS EXTRA_ENV EVAL_INDICES
set -uo pipefail

cd "$HOME/usersim"

: "${STAGE:?}" "${TAG:?}" "${SHARD_ID:?}" "${NUM_SHARDS:?}" "${MODEL:?}"
: "${WORKERS:?}" "${GCS_PREFIX:?}"
FAST="${FAST:-0}"
ACTIONS_PER_STEP="${ACTIONS_PER_STEP:-3}"
RESUME="${RESUME:-0}"
KEEP_VM="${KEEP_VM:-0}"
# 0 = leave the harness default (MAX_ACTIONS in capability/__init__).
MAX_ACTIONS="${MAX_ACTIONS:-0}"
# Space-separated KEY=VALUE pairs so an experiment arm can set its own flags
# without this script needing to know about them.
EXTRA_ENV="${EXTRA_ENV:-}"
EVAL_INDICES="${EVAL_INDICES:-}"

SHARD_TAG="${TAG}_shard${SHARD_ID}"
MANIFEST="results/capability/${STAGE}_mistral_${SHARD_TAG}.json"
LOG="$HOME/bakeoff_shard${SHARD_ID}.log"

set -a
# shellcheck disable=SC1091
source secrets/env
set +a
export BROWSER_USE_FAST="$FAST"
export BROWSER_USE_MAX_ACTIONS_PER_STEP="$ACTIONS_PER_STEP"

resume_flag=()
[[ "$RESUME" == "1" ]] && resume_flag=(--resume)
budget_flag=()
[[ "$MAX_ACTIONS" != "0" ]] && budget_flag=(--max-actions "$MAX_ACTIONS")

if [[ -n "$EXTRA_ENV" ]]; then
  for kv in $EXTRA_ENV; do export "${kv?}"; done
fi

eval_flag=()
[[ -n "$EVAL_INDICES" ]] && eval_flag=(--eval-indices "$EVAL_INDICES")

PYTHONPATH=src .venv/bin/python -m capability.run_mistral_bakeoff \
  --stage "$STAGE" --model "$MODEL" --workers "$WORKERS" --no-preflight \
  --num-shards "$NUM_SHARDS" --shard-id "$SHARD_ID" \
  --tag "$SHARD_TAG" "${budget_flag[@]}" "${eval_flag[@]}" "${resume_flag[@]}"
rc=$?
echo "BAKEOFF_EXIT=$rc"

# Judge creds are bundled on the VM, so re-score here rather than over SSH later.
PYTHONPATH=src .venv/bin/python -m capability.rejudge --manifest "$MANIFEST" || true

dest="${GCS_PREFIX}/${STAGE}/${TAG}"
gcloud storage cp "$MANIFEST" "${dest}/manifests/" --quiet || true
gcloud storage cp "$LOG" "${dest}/logs/" --quiet || true
if [[ -d results/capability/traces ]]; then
  gcloud storage cp --recursive results/capability/traces \
    "${dest}/traces/shard${SHARD_ID}/" --quiet || true
fi

marker="/tmp/shard${SHARD_ID}.done"
{
  echo "shard=$SHARD_ID"
  echo "exit=$rc"
  echo "finished=$(date -Is)"
} > "$marker"
gcloud storage cp "$marker" "${dest}/_done/" --quiet || true

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
