#!/bin/bash
# Box-side daily wrapper (proposed routine entrypoint). Builds today's lists from the warehouse (same rules as incremental.plan),
# creates one VM (vm_daily.sh), waits for DONE/FAILED (max 90 min), then ALWAYS deletes the VM and writes the README/merge files.
# Approved scope: about 700 pages a day, hard cap $1 a week (weekly_budget.py: no VM is started when the 7-day ledger has less than $0.02 left).
# The proxy credential is NOT passed in instance metadata: the VM reads it from Secret Manager (usersim-PROXY_URL) if that gives a value,
# else from the private object $B/secrets/proxy_url.txt (proxy_env.sh). It is never printed or logged (fetch_upvotes.py redacts error text).
# Whole-pool weekly follows rota (ask 20261103T0345): OFF. Switch on with ONE change, PHUP_FOLLOW_ROTA=1 below (or in the routine env),
# once the paid cap is confirmed. On: make_lists.py adds today's 1/7 of the non-active pool and reads active people daily (~6.7k pages/day,
# ~$1.7/week route-4 total), the weekly cap defaults to $2.50 instead of $1 and the wait goes to 150 min. Off: behaviour unchanged.
# usage: bash run_daily.sh [YYYY-MM-DD]   needs: /workspace/gcp-auth.sh
set -u; D=${1:-$(date -u +%F)}; HERE=$(cd $(dirname $0) && pwd)
export PHUP_FOLLOW_ROTA=${PHUP_FOLLOW_ROTA:-0}     # <- the switch (0 = off, 1 = whole-pool weekly rota)
WAIT_MIN=90; if [ "$PHUP_FOLLOW_ROTA" = 1 ]; then export PHUP_WEEKLY_CAP_USD=${PHUP_WEEKLY_CAP_USD:-2.5}; WAIT_MIN=150; fi
source /workspace/gcp-auth.sh >/dev/null 2>&1
B=gs://usersim-bakeoff-347838016394/usersim_sim; W=$B/raw/ph_people_daily/$D/work; VM=feeder-phdaily-$(echo $D | tr -d -)
REM=$(python3 $HERE/weekly_budget.py $D $B/raw/ph_people_daily) || { echo "weekly budget exhausted (left: ${REM:-?} USD); no VM started"; exit 3; }
MU=$(python3 -c "print(round(min(0.3, $REM * 0.3), 3))"); MF=$(python3 -c "print(round(min(4.0, $REM * 0.7), 3))")   # together at most what is left
python3 $HERE/make_lists.py $D /tmp/phd_$D || exit 1          # -> upvotes.txt, following.txt (follows only on Mondays unless PHUP_FOLLOW_ROTA=1)
gsutil -q cp $HERE/fetch_upvotes.py $HERE/proxy_env.sh /tmp/phd_$D/upvotes.txt /tmp/phd_$D/following.txt $W/
trap 'gcloud compute instances delete $VM --zone=us-central1-a --quiet >/dev/null 2>&1' EXIT
gcloud compute instances create $VM --zone=us-central1-a --machine-type=e2-standard-4 --subnet=primary-subnet \
  --image-family=debian-12 --image-project=debian-cloud --scopes=cloud-platform --metadata-from-file=startup-script=$HERE/vm_daily.sh \
  --metadata=work=$W,workers=4,max_usd_up=$MU,max_usd_fol=$MF,proxy_secret=usersim-PROXY_URL,secret_project=project-amer-scs-sandbox,proxy_gcs=$B/secrets/proxy_url.txt >/dev/null 2>&1 || exit 1
for i in $(seq $WAIT_MIN); do sleep 60; gsutil -q stat $W/DONE 2>/dev/null && break; gsutil -q stat $W/FAILED 2>/dev/null && break; done
python3 $HERE/summarize_daily.py $W $B/raw/ph_people_daily/$D     # README + fetch_state_rows.jsonl
