#!/usr/bin/env bash
# Cloud Agent environment build: gcloud/gsutil on default PATH for fleet GCP scripts.
set -euo pipefail
GCLOUD_ROOT="${HOME}/google-cloud-sdk"
if [[ ! -x "${GCLOUD_ROOT}/bin/gcloud" ]]; then
  curl -fsSL https://sdk.cloud.google.com | bash -s -- --disable-prompts --install-dir="${GCLOUD_ROOT}"
  "${GCLOUD_ROOT}/bin/gcloud" components update --quiet 2>/dev/null || true
fi
sudo ln -sf "${GCLOUD_ROOT}/bin/gcloud" /usr/local/bin/gcloud
sudo ln -sf "${GCLOUD_ROOT}/bin/gsutil" /usr/local/bin/gsutil
command -v gcloud >/dev/null
gcloud version | head -1
