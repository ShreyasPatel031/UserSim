#!/usr/bin/env bash
# Register the Google API hosts the governed agent calls (taken from the gateway's dry-run IAP audit logs).
# Under ENFORCED, any destination not registered in Agent Registry is denied, including the model endpoint.
set -euo pipefail; source "$(dirname "$0")/env.sh"
HOSTS="us-central1-aiplatform.googleapis.com us-central1-aiplatform.mtls.googleapis.com
iamcredentials.googleapis.com iamcredentials.mtls.googleapis.com
cloudresourcemanager.googleapis.com cloudresourcemanager.mtls.googleapis.com
telemetry.googleapis.com telemetry.mtls.googleapis.com
us-discoveryengine.googleapis.com us-discoveryengine.mtls.googleapis.com
oauth2.googleapis.com logging.googleapis.com logging.mtls.googleapis.com"
for h in $HOSTS; do
  id=${PREFIX}-ep-$(echo "${h%.googleapis.com}" | tr . -)
  curl -sS -o /dev/null -w "$id %{http_code}\n" -X POST -H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" \
    "https://agentregistry.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/services?serviceId=$id" \
    -d "{\"displayName\":\"$h\",\"description\":\"WellSky replica - Google API endpoint\",\"endpointSpec\":{\"type\":\"NO_SPEC\"},\"interfaces\":[{\"url\":\"https://$h\",\"protocolBinding\":\"JSONRPC\"}]}"
done
