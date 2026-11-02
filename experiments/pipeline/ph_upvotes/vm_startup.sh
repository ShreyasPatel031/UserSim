#!/bin/bash
# Spot-VM runner for fetch_upvotes.py. Metadata: mode (run name), workers, people (gs:// path), proxy_secret + secret_project (PROXY_URL is read from Secret Manager, not metadata).
exec > /var/log/job.log 2>&1
W=gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_upvotes_sample/work
md(){ curl -s -H Metadata-Flavor:Google http://metadata/computeMetadata/v1/instance/attributes/$1; }
MODE=$(md mode); NW=$(md workers); PEOPLE=$(md people); PROXY_URL=$(gcloud secrets versions access latest --secret="$(md proxy_secret)" --project="$(md secret_project)" 2>/dev/null)
[ -n "$PROXY_URL" ] || { echo FAILED_NO_PROXY_SECRET > /var/log/job.log; shutdown -h now; exit 1; }
export PROXY_URL
apt-get -qq update; apt-get -qq install -y python3-pip xvfb >/dev/null
pip install -q --break-system-packages "camoufox[geoip]==0.4.11" playwright && python3 -m playwright install-deps firefox >/dev/null && python3 -m camoufox fetch >/dev/null
mkdir -p /job && cd /job && gsutil -q cp $W/fetch_upvotes.py . && gsutil -q cp $PEOPLE people.txt
gsutil -q cp $W/out_$MODE.jsonl . 2>/dev/null   # resume
IF=$(ip route | awk '/default/{print $5;exit}'); R0=$(cat /sys/class/net/$IF/statistics/rx_bytes); T0=$(cat /sys/class/net/$IF/statistics/tx_bytes)
( while sleep 60; do gsutil -q cp /var/log/job.log $W/progress_$MODE.log; gsutil -q cp out_$MODE.jsonl $W/; done ) &
export PHUP_MODE=$(md phup_mode); PHUP_MODE=${PHUP_MODE:-light}
python3 fetch_upvotes.py people.txt out_$MODE.jsonl --workers ${NW:-4}
echo "NIC rx=$(( $(cat /sys/class/net/$IF/statistics/rx_bytes)-R0 )) tx=$(( $(cat /sys/class/net/$IF/statistics/tx_bytes)-T0 ))"
gsutil -q cp out_$MODE.jsonl $W/; gsutil -q cp /var/log/job.log $W/job_$MODE.log
shutdown -h now
