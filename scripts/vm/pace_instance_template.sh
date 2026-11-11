#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:?}}"
ZONE="${PACE_ZONE:?export PACE_ZONE}"
TEMPLATE="${PACE_TEMPLATE:-pace-feeder-e2-standard-2}"
MACHINE="${PACE_MACHINE:-e2-standard-2}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${PROJECT}.iam.gserviceaccount.com}"
FAMILY="${PACE_IMAGE_FAMILY_NAME:-pace-feeder}"
GC=(gcloud --account="$SA")

[[ -d /home/ubuntu/google-cloud-sdk/bin ]] && export PATH="/home/ubuntu/google-cloud-sdk/bin:$PATH"

"${GC[@]}" compute instance-templates delete "$TEMPLATE" --project="$PROJECT" --quiet 2>/dev/null || true
SUBNET="${PACE_SUBNET:-primary-subnet}"
REGION="${PACE_REGION:?export PACE_REGION}"
"${GC[@]}" compute instance-templates create "$TEMPLATE" \
  --project="$PROJECT" \
  --region="$REGION" \
  --machine-type="$MACHINE" \
  --network-interface=network=main-vpc,subnet="$SUBNET" \
  --service-account="$SA" --scopes=cloud-platform \
  --tags=allow-iap-ssh \
  --image-family="$FAMILY" --image-project="$PROJECT" \
  --boot-disk-size=20GB \
  --metadata-from-file "startup-script=$ROOT/pace_startup.sh"
echo "TEMPLATE=$TEMPLATE"
