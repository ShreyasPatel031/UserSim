#!/usr/bin/env bash
# Internal-only copy of the Onspring MCP (ingress=internal: reachable only from a VPC / PSC, not the internet),
# registered in Agent Registry, and the gateway's egress pointed at the private network with DNS peering.
set -euo pipefail; source "$(dirname "$0")/env.sh"
NAME=${PREFIX}-mcp-private
gcloud run deploy $NAME --source "$(dirname "$0")/mcp_onspring" --region "$REGION" \
  --service-account ${PREFIX}-mcp-onspring@$PROJECT_ID.iam.gserviceaccount.com \
  --ingress=internal --no-allow-unauthenticated --labels "$LABELS" --max-instances 1 --quiet 2>&1 | tail -2
URL=https://$NAME-$PROJECT_NUMBER.$REGION.run.app
echo "public reachability (expect 404/403 from Google Front End, not the app): $(curl -s -o /dev/null -w '%{http_code}' -X POST $URL/mcp)"
TOOLS=$(curl -sS -X POST "https://${PREFIX}-mcp-onspring-$PROJECT_NUMBER.$REGION.run.app/mcp" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences=https://${PREFIX}-mcp-onspring-$PROJECT_NUMBER.$REGION.run.app)" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | sed -n 's/^data: //p' | python3 -c 'import json,sys;print(json.dumps(json.load(sys.stdin)["result"]))')
BODY=$(python3 -c 'import json,sys;print(json.dumps({"displayName":"Onspring MCP (private)","description":"WellSky replica - internal-only Onspring MCP reached via PSC. Synthetic data.","mcpServerSpec":{"type":"TOOL_SPEC","content":json.loads(sys.argv[2])},"interfaces":[{"url":sys.argv[1]+"/mcp","protocolBinding":"JSONRPC"}]}))' "$URL" "$TOOLS")
curl -sS -o /dev/null -w "registry: %{http_code}\n" -X POST -H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" \
  "https://agentregistry.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/services?serviceId=$NAME" -d "$BODY"
