#!/usr/bin/env bash
# Deploy the mock off-runtime agent to Cloud Run and list it in Agent Registry via its A2A card (inventory only).
# For A2A_AGENT_CARD entries the registry rejects interfaces; the URL lives inside the card.
set -euo pipefail; source "$(dirname "$0")/env.sh"
NAME=${PREFIX}-ext-agent; SA=${PREFIX}-ext-agent@$PROJECT_ID.iam.gserviceaccount.com
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || gcloud iam service-accounts create ${PREFIX}-ext-agent --display-name="WellSky replica - off-runtime agent"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role=roles/modelarmor.user --condition=None --format=none
URL=https://$NAME-$PROJECT_NUMBER.$REGION.run.app
gcloud run deploy $NAME --source "$(dirname "$0")/external_agent" --region "$REGION" --service-account "$SA" \
  --no-allow-unauthenticated --set-env-vars "PUBLIC_URL=$URL,GOOGLE_CLOUD_PROJECT=$PROJECT_ID" --labels "$LABELS" --max-instances 1 --quiet 2>&1 | tail -1
CARD=$(curl -sS "$URL/.well-known/agent-card.json" -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences=$URL)")
BODY=$(python3 -c 'import json,sys;print(json.dumps({"displayName":"First Responder (mock, off-runtime)","description":"Hosted on Cloud Run: inventoried, not gateway-governed","agentSpec":{"type":"A2A_AGENT_CARD","content":json.loads(sys.argv[1])}}))' "$CARD")
curl -sS -o /dev/null -w "registry: %{http_code}\n" -X POST -H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" \
  "https://agentregistry.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/services?serviceId=$NAME" -d "$BODY"
