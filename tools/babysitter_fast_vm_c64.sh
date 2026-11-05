#!/bin/bash
cd /root; [ -f started ] && exit 0; touch started
B=gs://usersim-bakeoff-347838016394/usersim_sim
PORT=$(curl -s -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/bsit-port)
apt-get update -q >/dev/null 2>&1; apt-get install -y -q python3-pip xvfb libgtk-3-0 libasound2 libdbus-glib-1-2 libx11-xcb1 >/dev/null 2>&1
pip3 install -q --break-system-packages -U "camoufox[geoip]" >/dev/null 2>&1; python3 -m camoufox fetch >/dev/null 2>&1
mkdir -p /opt/ph/reuse /opt/ph/profiles && cd /opt/ph/reuse
gsutil -q cp $B/raw/_babysitter/pull/code/bsit_pgql.tgz reuse.tgz && tar xzf reuse.tgz
export PROXY_URL=$(gsutil -q cat $B/secrets/proxy_url.txt | python3 -c "import sys,urllib.parse as u;r=sys.stdin.read().strip();p=u.urlsplit(r);n=p.username if '__cr.' in p.username else p.username+'__cr.us';print(r.replace(p.username+':',n+':',1))")
export PROXY_PORT=$PORT PGQL_HTML_PER_MIN=0 PGQL_ORDER=pool
V=$(hostname)
( while sleep 30; do gsutil -q cp /root/run.log $B/raw/_babysitter/pull/run_$V.log 2>/dev/null; done ) &
xvfb-run -a -s "-screen 0 1920x1080x24" python3 pgql_test.py --token pgql:${V}_$(date -u +%H%M)_c64 > /root/run.log 2>&1; echo "EXIT $?" >> /root/run.log
gsutil -q cp /root/run.log $B/raw/_babysitter/pull/run_$V.log
