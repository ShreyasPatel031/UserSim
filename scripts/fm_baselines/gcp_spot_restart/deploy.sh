#!/usr/bin/env bash
# Deploy Eventarc + Cloud Tasks Spot restart function.
set -euo pipefail

PROJECT="${GCP_PROJECT:-$(gcloud config get-value project)}"
REGION="${REGION:-$(gcloud config get-value compute/region 2>/dev/null || true)}"
REGION="${REGION:-$(gcloud config get-value functions/region 2>/dev/null || true)}"
if [[ -z "${REGION}" || "${REGION}" == "(unset)" ]]; then
  echo "Set REGION (Cloud Functions / Compute region)" >&2
  exit 1
fi
FN_NAME="${FN_NAME:-usersim-spot-restart}"
RESTARTER_SA="usersim-spot-restarter@${PROJECT}.iam.gserviceaccount.com"
QUEUE="${QUEUE:-usersim-spot-retry}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "project=$PROJECT region=$REGION fn=$FN_NAME"

gcloud tasks queues describe "$QUEUE" --location="$REGION" --project="$PROJECT" >/dev/null 2>&1 \
  || gcloud tasks queues create "$QUEUE" --location="$REGION" --project="$PROJECT"

# Deploy HTTP function first (Tasks target). Eventarc trigger added after URL known.
gcloud functions deploy "$FN_NAME" \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source="$SRC_DIR" \
  --entry-point=spot_restart \
  --trigger-http \
  --no-allow-unauthenticated \
  --service-account="$RESTARTER_SA" \
  --memory=512Mi \
  --timeout=120s \
  --set-env-vars="GCP_PROJECT=${PROJECT},TASKS_LOCATION=${REGION},TASKS_QUEUE=${QUEUE},OIDC_SERVICE_ACCOUNT=${RESTARTER_SA},WATCH_LABEL_KEY=usersim-spot-watch,WATCH_LABEL_VALUE=true,RETRY_DELAY_SEC=60,MAX_ATTEMPTS=180" \
  --project="$PROJECT"

FN_URL="$(gcloud functions describe "$FN_NAME" --gen2 --region="$REGION" --project="$PROJECT" --format='value(serviceConfig.uri)')"
echo "FUNCTION_URL=$FN_URL"

gcloud functions deploy "$FN_NAME" \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source="$SRC_DIR" \
  --entry-point=spot_restart \
  --trigger-http \
  --no-allow-unauthenticated \
  --service-account="$RESTARTER_SA" \
  --memory=512Mi \
  --timeout=120s \
  --update-env-vars="FUNCTION_URL=${FN_URL}" \
  --project="$PROJECT"

# Allow restarter SA to invoke itself (Tasks OIDC)
gcloud run services add-iam-policy-binding "$FN_NAME" \
  --region="$REGION" \
  --member="serviceAccount:${RESTARTER_SA}" \
  --role="roles/run.invoker" \
  --project="$PROJECT" \
  --quiet

# Eventarc: Audit Log compute.instances.preempted → same Cloud Run service
TRIGGER="usersim-spot-preempted"
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

# Eventarc SA may appear after first trigger create — grant if present
PN="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:service-${PN}@gcp-sa-eventarc.iam.gserviceaccount.com" \
  --role="roles/eventarc.serviceAgent" --condition=None --quiet 2>/dev/null || true

echo "DEPLOYED $FN_NAME url=$FN_URL trigger=$TRIGGER queue=$QUEUE"
