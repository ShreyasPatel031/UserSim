#!/usr/bin/env bash
# One-liner for LOCAL machine (has gcloud): mint a short-lived signed URL for the cloud agent.
#   ./scripts/vm/sign_cloud_secrets_url.sh
set -euo pipefail
GCS_URI="${1:-gs://usersim-bakeoff-347838016394/secrets/usersim-cloud-secrets-latest.tgz}"
# 2 hours
gsutil signurl -d 2h secrets/vertex_adc.json "$GCS_URI" 2>/dev/null \
  || gcloud storage sign-url "$GCS_URI" --duration=2h --private-key-file=secrets/vertex_adc.json
