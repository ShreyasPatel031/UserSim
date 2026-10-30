#!/bin/bash
# hn-sim-1 job runner: installs Python deps once, then runs job scripts dropped in gs://<bucket>/usersim_sim/hn_jobs/queue/.
# Each job runs in /opt/work (code from hn_jobs/code.tgz, refreshed per job); its log goes to hn_jobs/done/.
Q=gs://usersim-bakeoff-347838016394/usersim_sim/hn_jobs
if [ ! -x /opt/exp/bin/python ]; then
  apt-get update -y && apt-get install -y python3-venv python3-pip
  python3 -m venv /opt/exp && /opt/exp/bin/pip install -q pandas pyarrow numpy scipy scikit-learn lightgbm requests \
    google-cloud-storage google-cloud-bigquery db-dtypes google-genai google-auth duckdb httpx "mcp<2"
fi
mkdir -p /opt/work
while true; do
  for j in $(gsutil ls $Q/queue/ 2>/dev/null | grep '\.sh$'); do
    n=$(basename $j)
    gsutil -q mv $j $Q/running/$n || continue
    rm -rf /opt/work/code && mkdir -p /opt/work/code && gsutil -q cp $Q/code.tgz /opt/work/ && tar xzf /opt/work/code.tgz -C /opt/work/code
    gsutil -q cp $Q/running/$n /opt/work/$n
    ( cd /opt/work/code && PATH=/opt/exp/bin:$PATH bash /opt/work/$n > /opt/work/$n.log 2>&1; echo "exit $?" >> /opt/work/$n.log
      gsutil -q cp /opt/work/$n.log $Q/done/$n.log; gsutil -q rm $Q/running/$n ) &
  done
  # keep live logs visible
  for l in /opt/work/*.sh.log; do [ -f "$l" ] && gsutil -q cp "$l" $Q/live/$(basename $l); done 2>/dev/null
  sleep 30
done
