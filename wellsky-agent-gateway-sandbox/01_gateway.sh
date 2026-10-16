#!/usr/bin/env bash
# Google-managed egress (AGENT_TO_ANYWHERE) Agent Gateway bound to the project's Agent Registry.
set -euo pipefail; source "$(dirname "$0")/env.sh"
curl -sS -X POST -H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" \
  "https://networkservices.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/agentGateways?agentGatewayId=$GW_NAME" \
  -d "{
    \"description\": \"WellSky replica - egress gateway for governed agents\",
    \"labels\": {\"owner\":\"searce-sc\",\"purpose\":\"wellsky-replica\"},
    \"googleManaged\": {\"governedAccessPath\": \"AGENT_TO_ANYWHERE\"},
    \"registries\": [\"//agentregistry.googleapis.com/projects/$PROJECT_ID/locations/$REGION\"]
  }"
