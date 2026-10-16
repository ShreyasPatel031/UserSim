#!/usr/bin/env bash
# Delete everything the WellSky replica created (all names prefixed wsky-). Leaves other teams' resources alone.
set -uo pipefail; source "$(dirname "$0")/env.sh"
H=(-H "Authorization: Bearer $(tok)")
# Model Armor service agent's DLP roles (roles/dlp.user, roles/dlp.reader) are left in place: other
# Model Armor users in the shared project may rely on them.
for id in 1985445595757674496 6114344854521643008 2960160179879936; do
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
AR=https://agentregistry.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/services
for s in $(curl -sS "${H[@]}" "$AR?pageSize=200" | python3 -c 'import json,sys;[print(x["name"].split("/")[-1]) for x in json.load(sys.stdin).get("services",[]) if x["name"].split("/")[-1].startswith("wsky-")]'); do
  curl -sS -X DELETE "${H[@]}" "$AR/$s" >/dev/null; done
curl -sS -X DELETE "${H[@]}" -H "X-Goog-User-Project: $PROJECT_ID" "https://dlp.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/inspectTemplates/wsky-phi-pii" >/dev/null
DE=https://us-discoveryengine.googleapis.com/v1/projects/$PROJECT_ID/locations/us/collections/default_collection
curl -sS -X DELETE "${H[@]}" -H "X-Goog-User-Project: $PROJECT_ID" "$DE/engines/${PREFIX}-kb-search" >/dev/null; sleep 20
curl -sS -X DELETE "${H[@]}" -H "X-Goog-User-Project: $PROJECT_ID" "$DE/dataStores/${PREFIX}-kb" >/dev/null
gcloud run services delete ${PREFIX}-mcp-onspring --region "$REGION" --quiet
gcloud iam service-accounts delete ${PREFIX}-mcp-onspring@$PROJECT_ID.iam.gserviceaccount.com --quiet
gcloud projects remove-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${PREFIX}-mcp-invoker@$PROJECT_ID.iam.gserviceaccount.com" --role=roles/run.invoker --all --format=none
gcloud iam service-accounts delete ${PREFIX}-mcp-invoker@$PROJECT_ID.iam.gserviceaccount.com --quiet
# Contingency-test resources: GE app, private MCP network, off-runtime agent.
curl -sS -X DELETE "${H[@]}" -H "X-Goog-User-Project: $PROJECT_ID" "$DE/engines/${PREFIX}-ge-app" >/dev/null
gcloud run services delete ${PREFIX}-mcp-private --region "$REGION" --quiet
gcloud run services delete ${PREFIX}-ext-agent --region "$REGION" --quiet
gcloud projects remove-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${PREFIX}-ext-agent@$PROJECT_ID.iam.gserviceaccount.com" --role=roles/modelarmor.user --all --format=none
gcloud iam service-accounts delete ${PREFIX}-ext-agent@$PROJECT_ID.iam.gserviceaccount.com --quiet
gcloud dns record-sets delete "*.run.app." --zone=${PREFIX}-priv-run --type=A --quiet
gcloud dns managed-zones delete ${PREFIX}-priv-run --quiet
gcloud compute forwarding-rules delete wskypsc2gapis --global --quiet
gcloud compute addresses delete ${PREFIX}-psc2gapis --global --quiet
gcloud compute network-attachments delete ${PREFIX}-psc-na --region "$REGION" --quiet
gcloud compute networks subnets delete ${PREFIX}-agw-subnet --region "$REGION" --quiet
gcloud compute networks delete ${PREFIX}-vnet --quiet
gcloud storage rm -r gs://${PREFIX}-replica-${PROJECT_NUMBER} --quiet
ORG=$(gcloud projects get-ancestors "$PROJECT_ID" --format='value(id,type)' | awk '$2=="organization"{print $1}')
for id in 1985445595757674496 6114344854521643008 2960160179879936; do
  M="principal://agents.global.org-$ORG.system.id.goog/resources/aiplatform/projects/$PROJECT_NUMBER/locations/$REGION/reasoningEngines/$id"
  gcloud projects remove-iam-policy-binding "$PROJECT_ID" --role=roles/discoveryengine.viewer --member="$M" --all --format=none
  gcloud projects remove-iam-policy-binding "$PROJECT_ID" --role=roles/iap.egressor --member="$M" --all --format=none
done
