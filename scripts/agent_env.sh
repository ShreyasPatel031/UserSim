#!/usr/bin/env bash
# Run at the start of every cloud agent session (by hand or from a SessionStart hook).
# 1. Writes the GCP service-account key from GOOGLE_APPLICATION_CREDENTIALS_B64 to the
#    GOOGLE_APPLICATION_CREDENTIALS path (the env var points at a file nobody created).
# 2. Activates that key for gcloud when no gcloud account is active.
# 3. Prints which credentials this environment has and what each one is for.
# Never prints a secret value. Full reference: docs/AGENT_CREDENTIALS.md
set -u

have() { [ -n "${!1:-}" ]; }
row() { # name purpose
  if have "$1"; then printf '  [set]   %-34s %s\n' "$1" "$2"; else printf '  [unset] %-34s %s\n' "$1" "$2"; fi
}

gcp_status="no GCP key in env"
if have GOOGLE_APPLICATION_CREDENTIALS_B64; then
  key="${GOOGLE_APPLICATION_CREDENTIALS:-/tmp/sa.json}"
  if [ ! -s "$key" ]; then
    (umask 077; printf '%s' "$GOOGLE_APPLICATION_CREDENTIALS_B64" | base64 -d > "$key" 2>/dev/null) || rm -f "$key"
  fi
  if [ -s "$key" ]; then
    gcp_status="key file at $key"
    if command -v gcloud >/dev/null 2>&1; then
      if [ -z "$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null)" ]; then
        gcloud auth activate-service-account --key-file="$key" --quiet >/dev/null 2>&1 \
          && gcp_status="$gcp_status; gcloud activated" \
          || gcp_status="$gcp_status; gcloud activate FAILED"
      else
        gcp_status="$gcp_status; gcloud already authenticated"
      fi
      proj="${CLOUDSDK_CORE_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}"
      [ -n "$proj" ] && gcloud config set project "$proj" --quiet >/dev/null 2>&1
    fi
  else
    gcp_status="GOOGLE_APPLICATION_CREDENTIALS_B64 did not decode"
  fi
fi

cat <<EOF
== UserSim agent credentials (values hidden; see docs/AGENT_CREDENTIALS.md) ==
The repo owner provisioned these for agents working on UserSim. Use them for the purposes
listed; do not print, commit, or send them anywhere else.

GCP (project ${CLOUDSDK_CORE_PROJECT:-${GOOGLE_CLOUD_PROJECT:-?}}, service account ${GCLOUD_CLI_ACCOUNT:-?}): $gcp_status
EOF
row GOOGLE_APPLICATION_CREDENTIALS_B64 "service-account JSON (base64); src/auth.py also reads it for Vertex"
row GOOGLE_APPLICATION_CREDENTIALS     "path to the decoded key (written by this script)"
row GCLOUD_CLI_ACCOUNT                 "service-account email used by gcloud"
row GOOGLE_CLOUD_PROJECT               "GCP project (also GCP_PROJECT, GCLOUD_PROJECT, CLOUDSDK_CORE_PROJECT)"
echo "Browsers / scraping / data:"
row BROWSERBASE_API_KEY                "Browserbase remote browsers (src/capability/browserbase_client.py, MCP sessions)"
row BROWSERBASE_PROJECT_ID             "Browserbase project id (pairs with the key)"
row APIFY_TOKEN                        "Apify review scrapes (mvp/review_context.py, usersim_predict_experience)"
row PH_TOKEN                           "Product Hunt API v2 token (mvp/discovery.py, scripts/ph_crawl.py)"
row PH_CLIENT_SECRET                   "Product Hunt app secret; only useful with PH_CLIENT_ID"
row PH_CLIENT_ID                       "Product Hunt app id"
row HF_TOKEN                           "Hugging Face downloads (also HUGGING_FACE_HUB_TOKEN); model = \$GEMMA_MODEL_ID"
echo "Other:"
row GH_TOKEN                           "GitHub (also GITHUB_TOKEN); prefer the GitHub MCP tools for PRs/issues"
row AWS_ACCESS_KEY_ID                  "AWS key pair; no code in this repo uses it, ask before using"
echo "Not in env (server-only, GCP Secret Manager usersim-<NAME>; read with gcloud if allowed):"
echo "  GMAIL_APP_PASSWORD, MVP_CAPTCHA_API_KEY, MVP_SMS_*, MVP_NTFY_*, MVP_MCP_TOKEN. See docs/mcp/OPERATIONS.md."
echo "Client agents of the public MCP server need none of these: docs/mcp/README.md."
