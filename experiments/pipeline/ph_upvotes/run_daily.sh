#!/bin/bash
# Box-side daily wrapper (proposed routine entrypoint). Builds today's lists from the warehouse (same rules as incremental.plan),
# creates one VM (vm_daily.sh), waits for DONE/FAILED (max 90 min), then ALWAYS deletes the VM and writes the README/merge files.
# usage: bash run_daily.sh [YYYY-MM-DD]   needs: /workspace/gcp-auth.sh, /workspace/secrets/proxy.env
set -u; D=${1:-$(date -u +%F)}; HERE=$(cd $(dirname $0) && pwd)
source /workspace/gcp-auth.sh >/dev/null 2>&1
B=gs://usersim-bakeoff-347838016394/usersim_sim; W=$B/raw/ph_people_daily/$D/work; VM=feeder-phdaily-$(echo $D | tr -d -)
python3 $HERE/make_lists.py $D /tmp/phd_$D || exit 1          # -> upvotes.txt, following.txt (follows only on Mondays)
gsutil -q cp $HERE/fetch_upvotes.py /tmp/phd_$D/upvotes.txt /tmp/phd_$D/following.txt $W/
set -a; . /workspace/secrets/proxy.env; set +a
trap 'gcloud compute instances delete $VM --zone=us-central1-a --quiet >/dev/null 2>&1' EXIT
gcloud compute instances create $VM --zone=us-central1-a --machine-type=e2-standard-4 --subnet=primary-subnet \
  --image-family=debian-12 --image-project=debian-cloud --scopes=storage-rw --metadata-from-file=startup-script=$HERE/vm_daily.sh \
  --metadata=work=$W,workers=4,max_usd_up=0.3,max_usd_fol=4.0,proxy="$PROXY_URL" >/dev/null 2>&1 || exit 1
for i in $(seq 90); do sleep 60; gsutil -q stat $W/DONE 2>/dev/null && break; gsutil -q stat $W/FAILED 2>/dev/null && break; done
python3 $HERE/summarize_daily.py $W $B/raw/ph_people_daily/$D     # README + fetch_state_rows.jsonl
