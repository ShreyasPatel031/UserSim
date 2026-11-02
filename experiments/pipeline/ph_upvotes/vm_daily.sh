#!/bin/bash
# Daily people refresh runner (VM startup script). Metadata: work (gs:// dir with fetch_upvotes.py, upvotes.txt, following.txt),
# proxy_secret + secret_project + proxy_gcs (PROXY_URL is read from Secret Manager, else from the private GCS object; never from metadata), workers, max_usd_up, max_usd_fol. Phases: ftest (5 people, following) -> upvotes -> following. Writes DONE / FAILED to $W.
exec > /var/log/job.log 2>&1
md(){ curl -s -H Metadata-Flavor:Google http://metadata/computeMetadata/v1/instance/attributes/$1; }
W=$(md work); NW=$(md workers); MU=$(md max_usd_up); MF=$(md max_usd_fol)
( while sleep 60; do gsutil -q cp /var/log/job.log $W/progress.log; gsutil -q cp /job/out_*.jsonl $W/ 2>/dev/null; done ) &
apt-get -qq update; apt-get -qq install -y python3-pip xvfb >/dev/null
pip install -q --break-system-packages "camoufox[geoip]==0.4.11" playwright && python3 -m playwright install-deps firefox >/dev/null && python3 -m camoufox fetch >/dev/null
mkdir -p /job && cd /job && gsutil -q cp $W/fetch_upvotes.py $W/proxy_env.sh $W/upvotes.txt $W/following.txt .
. ./proxy_env.sh
load_proxy "$(md proxy_secret)" "$(md secret_project)" "$(md proxy_gcs)" || { echo FAILED_NO_PROXY | gsutil -q cp - $W/FAILED; gsutil -q cp /var/log/job.log $W/; shutdown -h now; exit 1; }
for p in ftest upvotes following; do gsutil -q cp $W/out_$p.jsonl . 2>/dev/null; done   # resume
IF=$(ip route | awk '/default/{print $5;exit}'); R0=$(cat /sys/class/net/$IF/statistics/rx_bytes); T0=$(cat /sys/class/net/$IF/statistics/tx_bytes)
export PHUP_MODE=light
head -5 following.txt > ftest.txt
PHUP_PAGE=following python3 fetch_upvotes.py ftest.txt out_ftest.jsonl --workers 1 --max-usd 0.05
OK=$(python3 -c "import json;print(sum(1 for l in open('out_ftest.jsonl') if json.loads(l).get('status')==200 and 'following' in json.loads(l)))")
echo "ftest ok=$OK"
if [ "${OK:-0}" -lt 3 ]; then echo FAILED_FTEST | gsutil -q cp - $W/FAILED; gsutil -q cp out_ftest.jsonl /var/log/job.log $W/; shutdown -h now; fi
PHUP_PAGE=upvotes   python3 fetch_upvotes.py upvotes.txt   out_upvotes.jsonl   --workers ${NW:-4} --max-usd ${MU:-0.5}
PHUP_PAGE=following python3 fetch_upvotes.py following.txt out_following.jsonl --workers ${NW:-4} --max-usd ${MF:-3}
echo "NIC rx=$(( $(cat /sys/class/net/$IF/statistics/rx_bytes)-R0 )) tx=$(( $(cat /sys/class/net/$IF/statistics/tx_bytes)-T0 ))"
gsutil -q cp out_*.jsonl $W/; gsutil -q cp /var/log/job.log $W/job.log; echo ok | gsutil -q cp - $W/DONE
shutdown -h now
