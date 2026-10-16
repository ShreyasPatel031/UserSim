#!/usr/bin/env bash
# Point the egress gateway at the private network: PSC network attachment + DNS peering for run.app.
set -euo pipefail; source "$(dirname "$0")/env.sh"
NA=projects/$PROJECT_ID/regions/$REGION/networkAttachments/${PREFIX}-psc-na
curl -sS -X PATCH -H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" \
  "https://networkservices.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/agentGateways/$GW_NAME?updateMask=networkConfig" \
  -d "{\"networkConfig\":{\"egress\":{\"networkAttachment\":\"$NA\"},
       \"dnsPeeringConfig\":{\"domains\":[\"run.app.\"],\"targetProject\":\"$PROJECT_ID\",\"targetNetwork\":\"projects/$PROJECT_ID/global/networks/${PREFIX}-vnet\"}}}"
