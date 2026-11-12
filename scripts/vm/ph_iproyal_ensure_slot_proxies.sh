#!/usr/bin/env bash
# Keep fleet slot N on secrets/iproyal.pool line N; restart supervisor when proxy-url drifts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PATH="/home/ubuntu/google-cloud-sdk/bin:${PATH:-}"
# shellcheck source=/dev/null
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt" 2>/dev/null)}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
POOL="${PACE_IPROYAL_POOL:-$ROOT/secrets/iproyal.pool}"
[[ -f "$POOL" ]] || exit 0
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:-$("${GC[@]}" compute instances list --project="$GCP_PROJECT" --filter='name~feeder-fleet' --limit=1 --format='value(zone)')}"

_purl_abs() { local p=$1; [[ "$p" = /* ]] && echo "$p" || echo "$ROOT/$p"; }

mapfile -t LINES < <(grep -v '^[[:space:]]*#' "$POOL" | grep -v '^[[:space:]]*$' || true)
while IFS=$'\t' read -r slot _port; do
  [[ -z "$slot" || "$slot" == \#* ]] && continue
  idx=$((slot - 1))
  (( idx >= 0 && idx < ${#LINES[@]} )) || continue
  want="$(_purl_abs "${LINES[$idx]}")"
  [[ -f "$want" ]] || continue
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  have="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null \
    --command='curl -sf -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/proxy-url' 2>/dev/null || true)"
  want_host=$(python3 -c "import urllib.parse as u; print(u.urlparse(open('$want').read().strip()).hostname or '')")
  have_host=$(python3 -c "import urllib.parse as u,sys; print(u.urlparse(sys.argv[1].strip()).hostname or '')" "$have" 2>/dev/null || echo "")
  if [[ "$want_host" != "$have_host" ]]; then
    echo "iproyal bind $name $have_host -> $want_host"
    "${GC[@]}" compute instances add-metadata "$name" --zone="$ZONE" \
      --metadata-from-file="proxy-url=$want" >/dev/null
    "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null \
      --command='[[ -x /opt/ph/overlays/proxy_geo_sync.sh ]] && { B=$(grep -E "^PACE_GCS_VM_ROOT=" /opt/ph/pace.env | cut -d= -f2-); PACE_GCS_VM_ROOT="$B" bash /opt/ph/overlays/proxy_geo_sync.sh; }; sudo systemctl restart phsuper' 2>/dev/null || true
  fi
done <"$ART/slots.tsv"
