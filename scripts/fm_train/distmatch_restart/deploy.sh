#!/usr/bin/env bash
# Deploy the distmatch-only Spot restart function. Does not modify usersim-spot-restart.
set -euo pipefail

PROJECT="${GCP_PROJECT:-$(gcloud config get-value project)}"
# Region of the existing Spot restarter. Do not hardcode a location.
REGION="${REGION:-$(gcloud functions list --format=json | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(next(r["name"] for r in rows if r["name"].endswith("/functions/usersim-spot-restart")).split("/locations/")[1].split("/")[0])')}"
FN_NAME="${FN_NAME:-usersim-distmatch-restart}"
RESTARTER_SA="usersim-spot-restarter@${PROJECT}.iam.gserviceaccount.com"
QUEUE="${QUEUE:-usersim-spot-retry}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "project=$PROJECT region=$REGION fn=$FN_NAME"

gcloud functions deploy "$FN_NAME" \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source="$SRC_DIR" \
  --entry-point=distmatch_restart \
  --trigger-http \
  --no-allow-unauthenticated \
  --service-account="$RESTARTER_SA" \
  --memory=512Mi \
  --timeout=120s \
  --set-env-vars="GCP_PROJECT=${PROJECT},TASKS_LOCATION=${REGION},TASKS_QUEUE=${QUEUE},OIDC_SERVICE_ACCOUNT=${RESTARTER_SA},RETRY_DELAY_SEC=45" \
  --project="$PROJECT"

FN_URL="$(gcloud functions describe "$FN_NAME" --gen2 --region="$REGION" --project="$PROJECT" --format='value(serviceConfig.uri)')"
echo "FUNCTION_URL=$FN_URL"

gcloud functions deploy "$FN_NAME" \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source="$SRC_DIR" \
  --entry-point=distmatch_restart \
  --trigger-http \
  --no-allow-unauthenticated \
  --service-account="$RESTARTER_SA" \
  --memory=512Mi \
  --timeout=120s \
  --update-env-vars="FUNCTION_URL=${FN_URL}" \
  --project="$PROJECT"

gcloud run services add-iam-policy-binding "$FN_NAME" \
  --region="$REGION" \
  --member="serviceAccount:${RESTARTER_SA}" \
  --role="roles/run.invoker" \
  --project="$PROJECT" \
  --quiet

TRIGGER="usersim-distmatch-preempted"
if gcloud eventarc triggers describe "$TRIGGER" --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  echo "trigger exists: $TRIGGER"
else
  gcloud eventarc triggers create "$TRIGGER" \
    --location="$REGION" \
    --destination-run-service="$FN_NAME" \
    --destination-run-region="$REGION" \
    --destination-run-path="/" \
    --event-filters="type=google.cloud.audit.log.v1.written" \
    --event-filters="serviceName=compute.googleapis.com" \
    --event-filters="methodName=compute.instances.preempted" \
    --service-account="$RESTARTER_SA" \
    --project="$PROJECT"
fi

echo "DEPLOYED $FN_NAME url=$FN_URL trigger=$TRIGGER"
