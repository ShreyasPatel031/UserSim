#!/usr/bin/env bash
# Bake usersim-mvp-seed image family from a prepared youtube-seed VM.
#
# The image is a *dependency* image only: Xvfb, python3-venv, .venv with
# browser-use + Playwright Chromium. No signed-in Chrome profile, no SA keys.
#
# Usage:
#   scripts/vm/bake_mvp_seed_image.sh
#   SOURCE_VM=usersim-youtube-seed-0 ZONE=us-central1-a scripts/vm/bake_mvp_seed_image.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
ZONE="${ZONE:-us-central1-a}"
SOURCE_VM="${SOURCE_VM:-usersim-youtube-seed-0}"
IMAGE_FAMILY="${MVP_GCP_IMAGE_FAMILY:-usersim-mvp-seed}"
IMAGE_NAME="${IMAGE_NAME:-${IMAGE_FAMILY}-$(date -u +%Y%m%d-%H%M%S)}"
SA_JSON="${CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE:-$ROOT/secrets/sa.json}"

if [[ -f "$SA_JSON" ]]; then
  export CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE="$SA_JSON"
  export GOOGLE_APPLICATION_CREDENTIALS="$SA_JSON"
fi
export CLOUDSDK_CORE_PROJECT="$PROJECT"

echo "==> ensure $SOURCE_VM is RUNNING"
status=$(gcloud compute instances describe "$SOURCE_VM" --zone="$ZONE" --project="$PROJECT" --format='value(status)' || true)
if [[ "$status" == "TERMINATED" || "$status" == "STOPPED" ]]; then
  gcloud compute instances start "$SOURCE_VM" --zone="$ZONE" --project="$PROJECT" --quiet
fi

echo "==> wait for SSH"
for i in $(seq 1 40); do
  if gcloud compute ssh "$SOURCE_VM" --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --quiet --command='echo up' >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

echo "==> prepare deps on $SOURCE_VM (no secrets, no signed-in profile)"
gcloud compute ssh "$SOURCE_VM" --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --quiet --command='
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo systemctl stop unattended-upgrades.service 2>/dev/null || true
sudo killall apt-get apt dpkg 2>/dev/null || true
sleep 1
timeout 120 sudo apt-get install -y -qq xvfb python3-venv python3-pip || true
mkdir -p "$HOME/usersim"
cd "$HOME/usersim"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -U pip wheel
fi
.venv/bin/pip install -q "browser-use==0.13.8" playwright google-genai "google-auth==2.41.1" google-cloud-storage google-cloud-compute httpx pydantic
.venv/bin/playwright install chromium
sudo .venv/bin/playwright install-deps chromium 2>/dev/null || true
# Strip secrets / signed-in profile material from the image source.
rm -rf secrets/sa.json secrets/credentials.json secrets/identities.json \
       secrets/vertex_adc.json secrets/youtube_browser_profile \
       secrets/product_profiles secrets/youtube_storage_state.json \
       secrets/youtube_storage_state.json.signed 2>/dev/null || true
# Keep a minimal env stub so worker can source it without failing.
mkdir -p secrets
if [[ ! -f secrets/env ]]; then
  printf "GOOGLE_CLOUD_PROJECT=%s\nGCP_PROJECT=%s\n" \
    "'"$PROJECT"'" "'"$PROJECT"'" > secrets/env
fi
# Drop seed profile symlink if present.
rm -f secrets/youtube_browser_profile 2>/dev/null || true
echo PREP_OK
.venv/bin/python -c "import playwright; print(\"playwright ok\")"
test -x .venv/bin/python
command -v Xvfb
'

echo "==> stop $SOURCE_VM for consistent image"
gcloud compute instances stop "$SOURCE_VM" --zone="$ZONE" --project="$PROJECT" --quiet

echo "==> create image $IMAGE_NAME (family=$IMAGE_FAMILY)"
gcloud compute images create "$IMAGE_NAME" \
  --project="$PROJECT" \
  --source-disk="$SOURCE_VM" \
  --source-disk-zone="$ZONE" \
  --family="$IMAGE_FAMILY" \
  --description="UserSim MVP dependency image: Xvfb + venv + Playwright Chromium (anonymous browsing). No SA keys, no signed-in profiles." \
  --quiet

echo "==> leave $SOURCE_VM TERMINATED (template only)"
# Already stopped; leave it.
gcloud compute images describe "$IMAGE_NAME" --project="$PROJECT" --format='yaml(name,family,status,diskSizeGb)' 

echo "BAKE_OK family=$IMAGE_FAMILY name=$IMAGE_NAME"
echo "Set MVP_GCP_IMAGE_FAMILY=$IMAGE_FAMILY"
