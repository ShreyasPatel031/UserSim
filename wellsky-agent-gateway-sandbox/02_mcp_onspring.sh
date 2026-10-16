#!/usr/bin/env bash
# Deploy the Onspring mock MCP server to Cloud Run (IAM-authenticated, no public invoke).
set -euo pipefail; source "$(dirname "$0")/env.sh"
SA=${PREFIX}-mcp-onspring@$PROJECT_ID.iam.gserviceaccount.com
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create ${PREFIX}-mcp-onspring --display-name="WellSky replica - Onspring MCP runtime"
gcloud run deploy ${PREFIX}-mcp-onspring --source "$(dirname "$0")/mcp_onspring" --region "$REGION" \
  --service-account "$SA" --no-allow-unauthenticated --labels "$LABELS" --max-instances 2 --quiet
