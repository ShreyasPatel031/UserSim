#!/usr/bin/env bash
# Bake golden image from a ready feeder disk snapshot.
set -euo pipefail
PROJECT="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:?}}"
ZONE="${PACE_ZONE:?export PACE_ZONE}"
SOURCE="${1:?feeder-phpeople-1}"
SNAP="${PACE_SNAPSHOT_NAME:-pace-feeder-src-$(date -u +%Y%m%d%H%M%S)}"
IMAGE="${PACE_IMAGE_NAME:-pace-feeder-golden-$(date -u +%Y%m%d)}"
FAMILY="${PACE_IMAGE_FAMILY_NAME:-pace-feeder}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")

DISK=$("${GC[@]}" compute instances describe "$SOURCE" --project="$PROJECT" --zone="$ZONE" \
  --format='value(disks[0].source.basename())')
echo "Snapshot $SNAP from disk $DISK"
"${GC[@]}" compute disks snapshot "$DISK" --project="$PROJECT" --zone="$ZONE" --snapshot-names="$SNAP" --quiet
for _ in $(seq 1 120); do
  [[ $("${GC[@]}" compute snapshots describe "$SNAP" --project="$PROJECT" --format='value(status)')" == READY ]] && break
  sleep 3
done
"${GC[@]}" compute images create "$IMAGE" --project="$PROJECT" --source-snapshot="$SNAP" --family="$FAMILY" --quiet
echo "IMAGE=$IMAGE FAMILY=$FAMILY"
