#!/usr/bin/env bash
# Cloud Run MCP needs an ID token, which Agent Identity can't mint for itself. Pattern from Google's samples:
# a dedicated invoker SA with run.invoker on the MCP service; only the agent's principal may mint its ID tokens.
set -euo pipefail; source "$(dirname "$0")/env.sh"
ENGINE_ID=${1:?reasoningEngine numeric id}
SA=${PREFIX}-mcp-invoker@$PROJECT_ID.iam.gserviceaccount.com
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create ${PREFIX}-mcp-invoker --display-name="WellSky replica - MCP invoker for governed agents"
# Sandbox: project-level run.invoker (the deployer SA can't set service-level IAM, and a resource.name IAM
# condition on run.invoker did not take effect in testing). Production: bind run.invoker on the MCP service only.
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role=roles/run.invoker --condition=None --format=none
ORG=$(gcloud projects get-ancestors "$PROJECT_ID" --format='value(id,type)' | awk '$2=="organization"{print $1}')
P="principal://agents.global.org-$ORG.system.id.goog/resources/aiplatform/projects/$PROJECT_NUMBER/locations/$REGION/reasoningEngines/$ENGINE_ID"
gcloud iam service-accounts add-iam-policy-binding "$SA" --member="$P" \
  --role=roles/iam.serviceAccountOpenIdTokenCreator --format=none
echo "invoker $SA usable by $P"
