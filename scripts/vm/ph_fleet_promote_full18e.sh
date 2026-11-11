#!/usr/bin/env bash
# Point fleet _code/reuse.tgz at Population full18e (follow-list re-page fix).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
export GCP_PROJECT MVP_GCS_BUCKET
VM_GCS="${PACE_VM_GCS:-gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
SRC="gs://${MVP_GCS_BUCKET}/usersim_sim/raw/population/builds/full18e_candidate.tgz"
DST="${VM_GCS}/_code/reuse.tgz"
FLEET_PKG=full18e_candidate.tgz
FLEET_PKG_MD5=emGHSIIIgQ73nRE8WMwLiw==

gcloud --account="${PACE_SERVICE_ACCOUNT}" storage cp "$SRC" "$DST"
got="$(gcloud storage hash "$DST" 2>/dev/null | awk '/md5_hash:/{print $2}')"
[[ "$got" == "$FLEET_PKG_MD5" ]] || { echo "md5 mismatch got=$got want=$FLEET_PKG_MD5" >&2; exit 1; }
echo "promoted reuse.tgz -> full18e md5=$FLEET_PKG_MD5"
