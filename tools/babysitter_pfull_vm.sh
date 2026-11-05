#!/bin/bash
cd /root; [ -f started ] && exit 0; touch started
B=gs://usersim-bakeoff-347838016394/usersim_sim
PORT=$(curl -s -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/bsit-port)
apt-get update -q >/dev/null 2>&1; apt-get install -y -q python3-pip xvfb libgtk-3-0 libasound2 libdbus-glib-1-2 libx11-xcb1 >/dev/null 2>&1
pip3 install -q --break-system-packages -U "camoufox[geoip]" >/dev/null 2>&1; python3 -m camoufox fetch >/dev/null 2>&1
mkdir -p /opt/ph/reuse/out /opt/ph/profiles && cd /opt/ph/reuse
gsutil -q cp $B/raw/ph_population/people_live/vm/_code/staging/reuse_0227Z_pfull2.tgz reuse.tgz && tar xzf reuse.tgz
export PROXY_URL=$(gsutil -q cat $B/secrets/proxy_url.txt | python3 -c "import sys,urllib.parse as u;r=sys.stdin.read().strip();p=u.urlsplit(r);n=p.username if '__cr.' in p.username else p.username+'__cr.us';print(r.replace(p.username+':',n+':',1))")
export PROXY_PORT=$PORT PDEEP_MODE=full PDEEP_K=16 PDEEP_TABS=1 PDEEP_RAMP=1:150
V=$(hostname)
echo "go" | gsutil -q cp - $B/raw/ph_population/people_live/vm/GO.$V
( while sleep 30; do gsutil -q cp /root/run.log $B/raw/_babysitter/pull/run_$V.log 2>/dev/null; done ) &
python3 pdeep.py --token pfull:${V}_$(date -u +%H%M) > /root/run.log 2>&1; echo "EXIT $?" >> /root/run.log
gsutil -q cp /root/run.log $B/raw/_babysitter/pull/run_$V.log
