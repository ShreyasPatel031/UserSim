#!/usr/bin/env bash
# Deploy Pub/Sub push bridge: agent-msgs → Cursor API steer (no agent polling).
set -euo pipefail
[[ -d /home/ubuntu/google-cloud-sdk/bin ]] && export PATH="/home/ubuntu/google-cloud-sdk/bin:${PATH:-}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
PROJECT="${AGENT_MSGS_PROJECT:-${GCP_PROJECT:?}}"
REGION="${FLEET_WAKE_REGION:-}"
if [[ -z "$REGION" ]]; then
  REGION="$(gcloud config get-value run/region 2>/dev/null | tr -d '\r' || true)"
fi
if [[ -z "$REGION" ]]; then
  REGION="$(gcloud run services list --project="$PROJECT" --filter="metadata.name=$SERVICE" --format='value(metadata.labels.cloud.googleapis.com/location)' 2>/dev/null | head -1)"
fi
[[ -n "$REGION" ]] || { echo "set FLEET_WAKE_REGION" >&2; exit 1; }
SERVICE="fleet-cursor-wake"
SUB="fleet-cursor-wake"
TOPIC="${AGENT_MSGS_TOPIC:-agent-msgs}"
SRC="$ROOT/deploy/fleet_cursor_wake"
FILTER='attributes.to = "fleet-cursor" OR (attributes.to = "all" AND attributes.from != "fleet-cursor")'

SECRET_NAME="cursor-fleet-api-key"
SECRET_ARGS=()
if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT" >/dev/null 2>&1; then
  SECRET_ARGS=(--set-secrets="CURSOR_API_KEY=${SECRET_NAME}:latest")
  echo "Mounting Secret Manager $SECRET_NAME on Cloud Run."
elif [[ -n "${FLEET_CURSOR_WAKE_API_KEY:-}" || -n "${CURSOR_API_KEY:-}" ]]; then
  _wake_key="${FLEET_CURSOR_WAKE_API_KEY:-$CURSOR_API_KEY}"
  echo "Creating $SECRET_NAME from FLEET_CURSOR_WAKE_API_KEY in shell..." >&2
  printf '%s' "$_wake_key" | gcloud secrets create "$SECRET_NAME" \
    --project="$PROJECT" --replication-policy=automatic --data-file=- 2>/dev/null \
    || printf '%s' "$_wake_key" | gcloud secrets versions add "$SECRET_NAME" --project="$PROJECT" --data-file=-
  SECRET_ARGS=(--set-secrets="CURSOR_API_KEY=${SECRET_NAME}:latest")
else
  echo "WARN: no $SECRET_NAME and no CURSOR_API_KEY — steer will 503 until secret exists (Cursor Dashboard → API Keys)." >&2
fi

echo "Deploying Cloud Run $SERVICE in $PROJECT ($REGION)..."
gcloud run deploy "$SERVICE" \
  --project="$PROJECT" \
  --region="$REGION" \
  --source="$SRC" \
  --clear-base-image \
  --no-allow-unauthenticated \
  --set-env-vars="FUNCTION_TARGET=wake,MVP_GCS_BUCKET=${MVP_GCS_BUCKET:-},FLEET_CURSOR_BC_ID=${FLEET_CURSOR_BC_ID:-${CURSOR_CONVERSATION_ID:-}}" \
  "${SECRET_ARGS[@]}" \
  --quiet

URL="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(status.url)')"
SA="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(spec.template.spec.serviceAccountName)')"

if gcloud pubsub subscriptions describe "$SUB" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud pubsub subscriptions update "$SUB" \
    --project="$PROJECT" \
    --push-endpoint="${URL}" \
    --push-auth-service-account="$SA" \
    --push-auth-token-audience="$URL" \
    --quiet
else
  gcloud pubsub subscriptions create "$SUB" \
    --project="$PROJECT" \
    --topic="$TOPIC" \
    --push-endpoint="${URL}" \
    --push-auth-service-account="$SA" \
    --push-auth-token-audience="$URL" \
    --message-filter="$FILTER" \
    --ack-deadline=30 \
    --quiet
fi

echo "OK push subscription=$SUB endpoint=$URL filter=$FILTER"
echo "Publish bc id: bash scripts/vm/ph_fleet_cursor_publish_bc.sh"
echo "Peers: ph_fleet_agent_relay.sh fleet-cursor <from> 'urgent text'"
