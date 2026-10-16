#!/usr/bin/env bash
# Synthetic WellSky knowledge base: unstructured data store + search engine (what the DE API agent queries).
set -euo pipefail; source "$(dirname "$0")/env.sh"
DE_LOC=${DE_LOC:-us}
DE=https://${DE_LOC}-discoveryengine.googleapis.com/v1/projects/$PROJECT_ID/locations/${DE_LOC}/collections/default_collection
H=(-H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" -H "X-Goog-User-Project: $PROJECT_ID")
curl -sS -X POST "${H[@]}" "$DE/dataStores?dataStoreId=${PREFIX}-kb" -d '{
  "displayName": "wsky-kb (WellSky replica, synthetic)", "industryVertical": "GENERIC",
  "solutionTypes": ["SOLUTION_TYPE_SEARCH"], "contentConfig": "CONTENT_REQUIRED"}'
sleep 20
curl -sS -X POST "${H[@]}" "$DE/dataStores/${PREFIX}-kb/branches/default_branch/documents:import" -d "{
  \"gcsSource\": {\"inputUris\": [\"gs://${PREFIX}-replica-${PROJECT_NUMBER}/kb/*.txt\"], \"dataSchema\": \"content\"},
  \"reconciliationMode\": \"FULL\"}"
curl -sS -X POST "${H[@]}" "$DE/engines?engineId=${PREFIX}-kb-search" -d "{
  \"displayName\": \"wsky-kb-search\", \"solutionType\": \"SOLUTION_TYPE_SEARCH\",
  \"dataStoreIds\": [\"${PREFIX}-kb\"],
  \"searchEngineConfig\": {\"searchTier\": \"SEARCH_TIER_ENTERPRISE\", \"searchAddOns\": [\"SEARCH_ADD_ON_LLM\"]}}"
