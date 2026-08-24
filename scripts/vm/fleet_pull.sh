#!/usr/bin/env bash
# Pull one shard's manifest off its VM. Meant to be fanned out with xargs -P.
#   seq 0 24 | xargs -P 25 -n1 ./scripts/vm/fleet_pull.sh
set -uo pipefail

i="$1"
STAGE="${STAGE:-full100}"
PREFIX="${FLEET_PREFIX:-usersim-bu-f100}"
TAG="${FLEET_TAG:-mistral-small-2603_m33_stage1_fleet}"
ZONE="${GCP_ZONE:-us-central1-a}"
PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
DEST="${DEST:-results/capability}"

file="${STAGE}_mistral_${TAG}_shard${i}.json"
if gcloud compute scp "${PREFIX}-${i}:~/usersim/results/capability/${file}" "${DEST}/" \
     --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --quiet >/dev/null 2>&1; then
  echo "ok    $i"
else
  echo "MISS  $i"
fi
