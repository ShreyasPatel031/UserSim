#!/usr/bin/env bash
# Allow a governed agent to egress through the gateway to registered destinations, except one MCP tool.
# Demonstrates per-tool policy: onspring list_governance_records allowed, get_governance_record denied.
# The empty tool name must stay allowed so MCP handshakes (initialize, tools/list) pass.
set -euo pipefail; source "$(dirname "$0")/env.sh"
ENGINE_ID=${1:?reasoningEngine numeric id}
ORG=$(gcloud projects get-ancestors "$PROJECT_ID" --format='value(id,type)' | awk '$2=="organization"{print $1}')
P="principal://agents.global.org-$ORG.system.id.goog/resources/aiplatform/projects/$PROJECT_NUMBER/locations/$REGION/reasoningEngines/$ENGINE_ID"
COND=$(mktemp); cat > "$COND" <<'YAML'
title: wsky-deny-onspring-get-record
description: Governed agents may call every registered destination except the Onspring get_governance_record tool
expression: api.getAttribute('iap.googleapis.com/mcp.toolName', '') != 'get_governance_record'
YAML
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="$P" --role=roles/iap.egressor --format=none --condition-from-file="$COND"
rm -f "$COND"
echo "iap.egressor (except get_governance_record) granted to $P"
