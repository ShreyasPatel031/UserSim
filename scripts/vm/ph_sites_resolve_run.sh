#!/usr/bin/env bash
# Run a nightly own-IP job on one fleet slot: pause that slot's historical work, run the job, then return the slot
# to historical work (supervisor restart via ph_fleet_roll_patches.sh, queue kept).
#   bash scripts/vm/ph_sites_resolve_run.sh <slot> <day> [day...]                       product-site resolution
#   JOB_SCRIPT=ph_maker_headers.py bash scripts/vm/ph_sites_resolve_run.sh <slot> <day>  maker header read
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
export GCP_PROJECT PACE_ZONE MVP_GCS_BUCKET
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
JOB="${JOB_SCRIPT:-ph_sites_resolve.py}"
SLOT="$1"; shift
VM="feeder-fleet-${RUN_ID}-${SLOT}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
RAW="gs://${MVP_GCS_BUCKET}/usersim_sim/raw"
LOG="$ROOT/results/ph_fleet_full/${RUN_ID}/sites_resolve.log"

"${GC[@]}" compute scp "$ROOT/scripts/vm/$JOB" "$ROOT/scripts/vm/ph_maker_headers.py" "$VM:/tmp/" --zone="$PACE_ZONE" --tunnel-through-iap --quiet >/dev/null 2>&1
# The proxy env is read from the slot's own running process into a root-only file on the VM and removed after.
"${GC[@]}" compute ssh "$VM" --zone="$PACE_ZONE" --tunnel-through-iap --quiet --command="set -e
pid=\$(pgrep -f '[p]deep.py|[p]h_batch.py' | head -1 || true)
if [[ -n \"\$pid\" ]]; then sudo cat /proc/\$pid/environ | tr '\0' '\n' | grep -E '^(PROXY_URL|PROXY_PORT)=' | sed 's/^/export /' | sudo tee /root/sites_env.sh >/dev/null; fi
sudo test -s /root/sites_env.sh
sudo systemctl stop phsuper || true
sudo pkill -f '[p]deep.py|[p]h_batch.py' 2>/dev/null || true; sudo pkill -f '[c]amoufox' 2>/dev/null || true
sleep 3
sudo bash -c 'source /root/sites_env.sh; cd /opt/ph/reuse; timeout 10800 /opt/venv/bin/python /tmp/$JOB --raw $RAW $*' 2>&1 | grep -v setlocale
sudo rm -f /root/sites_env.sh" 2>/dev/null | tee -a "$LOG"
ONLY_SLOTS="$SLOT" SKIP_UPLOAD=1 PRESERVE_QUEUE_CACHE=1 PACE_FLEET_RUN_ID="$RUN_ID" bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh" 2>&1 | grep -E "roll|rror" | tee -a "$LOG"
