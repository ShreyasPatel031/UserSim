#!/usr/bin/env bash
# Register the Onspring mock MCP server in Agent Registry with its tool spec (pulled live from tools/list).
set -euo pipefail; source "$(dirname "$0")/env.sh"
URL=$(gcloud run services describe ${PREFIX}-mcp-onspring --region "$REGION" --format='value(status.url)')
TOOLS=$(curl -sS -X POST "$URL/mcp" -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences=$URL)" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | sed -n 's/^data: //p' | python3 -c 'import json,sys;print(json.dumps(json.load(sys.stdin)["result"]))')
BODY=$(python3 - "$URL" "$TOOLS" <<'PY'
import json, sys
url, tools = sys.argv[1], sys.argv[2]
print(json.dumps({
  "displayName": "Onspring MCP (mock)",
  "description": "WellSky replica - read-only Onspring governance records. Synthetic data.",
  "mcpServerSpec": {"type": "TOOL_SPEC", "content": json.loads(tools)},
  "interfaces": [{"url": url + "/mcp", "protocolBinding": "JSONRPC"}],
}))
PY
)
curl -sS -X POST -H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" \
  "https://agentregistry.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/services?serviceId=${PREFIX}-mcp-onspring" -d "$BODY"
