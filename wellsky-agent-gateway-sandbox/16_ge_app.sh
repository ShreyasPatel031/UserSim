#!/usr/bin/env bash
# Gemini Enterprise app of our own (us location, wsky-kb data store) for the gateway-binding test.
set -euo pipefail; source "$(dirname "$0")/env.sh"
DE=https://us-discoveryengine.googleapis.com/v1/projects/$PROJECT_ID/locations/us/collections/default_collection
curl -sS -X POST -H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" -H "X-Goog-User-Project: $PROJECT_ID" \
  "$DE/engines?engineId=${PREFIX}-ge-app" -d "{
  \"displayName\": \"wsky-ge-app (WellSky replica)\", \"solutionType\": \"SOLUTION_TYPE_SEARCH\",
  \"industryVertical\": \"GENERIC\", \"appType\": \"APP_TYPE_INTRANET\",
  \"dataStoreIds\": [\"${PREFIX}-kb\"],
  \"searchEngineConfig\": {\"searchTier\": \"SEARCH_TIER_ENTERPRISE\", \"searchAddOns\": [\"SEARCH_ADD_ON_LLM\"]}}"
