# Source this before running any script here.
export PROJECT_ID=project-amer-scs-sandbox
export REGION=us-central1
export PREFIX=wsky
export GW_NAME=${PREFIX}-egress-gw
export LABELS="owner=searce-sc,purpose=wellsky-agent-gateway-replica"
unset CLOUDSDK_AUTH_ACCESS_TOKEN
gcloud config set project "$PROJECT_ID" >/dev/null 2>&1
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
tok(){ gcloud auth print-access-token; }
# Python SDKs read ADC from a key file; decode the base64 env secret into the session scratchpad.
if [ -n "${GOOGLE_APPLICATION_CREDENTIALS_JSON:-}" ] && [ -n "${WSKY_KEY_FILE:-}" ]; then
  printf '%s' "$GOOGLE_APPLICATION_CREDENTIALS_JSON" | base64 -d > "$WSKY_KEY_FILE"; chmod 600 "$WSKY_KEY_FILE"
  export GOOGLE_APPLICATION_CREDENTIALS="$WSKY_KEY_FILE"
fi
