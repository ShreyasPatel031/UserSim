#!/usr/bin/env bash
# Grant an agent's own Agent Identity principal read/search on Discovery Engine (least privilege: viewer).
set -euo pipefail; source "$(dirname "$0")/env.sh"
ENGINE_ID=${1:?reasoningEngine numeric id}
ORG=$(gcloud projects get-ancestors "$PROJECT_ID" --format='value(id,type)' | awk '$2=="organization"{print $1}')
P="principal://agents.global.org-$ORG.system.id.goog/resources/aiplatform/projects/$PROJECT_NUMBER/locations/$REGION/reasoningEngines/$ENGINE_ID"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="$P" --role=roles/discoveryengine.viewer --condition=None --format=none
echo "granted roles/discoveryengine.viewer to $P"
