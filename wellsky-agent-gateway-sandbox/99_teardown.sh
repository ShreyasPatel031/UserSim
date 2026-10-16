#!/usr/bin/env bash
# Delete everything the WellSky replica created (all names prefixed wsky-). Leaves other teams' resources alone.
set -uo pipefail; source "$(dirname "$0")/env.sh"
H=(-H "Authorization: Bearer $(tok)")
for id in 1985445595757674496 6349433634679685120; do
  curl -sS -X DELETE "${H[@]}" "https://$REGION-aiplatform.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/reasoningEngines/$id?force=true" >/dev/null
done
for p in ${PREFIX}-gw-iap ${PREFIX}-gw-model-armor; do
  curl -sS -X DELETE "${H[@]}" "https://networksecurity.googleapis.com/v1beta1/projects/$PROJECT_ID/locations/$REGION/authzPolicies/$p" >/dev/null; done
sleep 30
for e in ${PREFIX}-iap-dryrun ${PREFIX}-iap-enforced ${PREFIX}-model-armor; do
  curl -sS -X DELETE "${H[@]}" "https://networkservices.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/authzExtensions/$e" >/dev/null; done
curl -sS -X DELETE "${H[@]}" "https://networkservices.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/agentGateways/$GW_NAME" >/dev/null
for t in request response; do
  curl -sS -X DELETE "${H[@]}" "https://modelarmor.$REGION.rep.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/templates/${PREFIX}-$t" >/dev/null; done
curl -sS -X DELETE "${H[@]}" "https://agentregistry.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/services/${PREFIX}-mcp-onspring" >/dev/null
DE=https://us-discoveryengine.googleapis.com/v1/projects/$PROJECT_ID/locations/us/collections/default_collection
curl -sS -X DELETE "${H[@]}" -H "X-Goog-User-Project: $PROJECT_ID" "$DE/engines/${PREFIX}-kb-search" >/dev/null; sleep 20
curl -sS -X DELETE "${H[@]}" -H "X-Goog-User-Project: $PROJECT_ID" "$DE/dataStores/${PREFIX}-kb" >/dev/null
gcloud run services delete ${PREFIX}-mcp-onspring --region "$REGION" --quiet
gcloud iam service-accounts delete ${PREFIX}-mcp-onspring@$PROJECT_ID.iam.gserviceaccount.com --quiet
gcloud storage rm -r gs://${PREFIX}-replica-${PROJECT_NUMBER} --quiet
ORG=$(gcloud projects get-ancestors "$PROJECT_ID" --format='value(id,type)' | awk '$2=="organization"{print $1}')
for id in 1985445595757674496 6349433634679685120; do
  gcloud projects remove-iam-policy-binding "$PROJECT_ID" --role=roles/discoveryengine.viewer --condition=None --format=none \
    --member="principal://agents.global.org-$ORG.system.id.goog/resources/aiplatform/projects/$PROJECT_NUMBER/locations/$REGION/reasoningEngines/$id"
done
