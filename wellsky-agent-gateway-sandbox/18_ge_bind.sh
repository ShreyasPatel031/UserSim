#!/usr/bin/env bash
# Bind (or unbind) the wsky Gemini Enterprise app to the egress gateway.
#   ./18_ge_bind.sh bind | unbind | show
set -euo pipefail; source "$(dirname "$0")/env.sh"
E=https://us-discoveryengine.googleapis.com/v1/projects/$PROJECT_NUMBER/locations/us/collections/default_collection/engines/${PREFIX}-ge-app
H=(-H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" -H "X-Goog-User-Project: $PROJECT_ID")
case "${1:-show}" in
  bind)   curl -sS -X PATCH "${H[@]}" "$E?updateMask=agentGatewaySetting.defaultEgressAgentGateway.name" \
            -d "{\"agentGatewaySetting\":{\"defaultEgressAgentGateway\":{\"name\":\"projects/$PROJECT_ID/locations/$REGION/agentGateways/$GW_NAME\"}}}" | head -c 400; echo ;;
  unbind) curl -sS -X PATCH "${H[@]}" "$E?updateMask=agentGatewaySetting" -d '{"agentGatewaySetting":{}}' | head -c 400; echo ;;
esac
curl -sS "${H[@]}" "$E" | python3 -c 'import json,sys;d=json.load(sys.stdin);print("binding:", json.dumps(d.get("agentGatewaySetting")))'
