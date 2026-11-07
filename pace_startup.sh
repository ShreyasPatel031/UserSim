#!/bin/bash
# Pace feeder boot: install Camoufox once, refresh reuse.tgz, run phsuper (queue worker).
exec >> /var/log/phreuse_start.log 2>&1
mkdir -p /opt/ph
curl -sf -H Metadata-Flavor:Google \
  http://metadata.google.internal/computeMetadata/v1/instance/attributes/ph-strategy-env \
  >/opt/ph/strategy.env 2>/dev/null || true
if [[ -f /opt/ph/strategy.env ]]; then
  set -a
  # shellcheck source=/dev/null
  source /opt/ph/strategy.env
  set +a
fi
B="${PACE_GCS_VM_ROOT:-gs://[REDACTED]/usersim_sim/raw/ph_population/people_live/vm}"
if [ ! -x /opt/venv/bin/python ]; then
apt-get update -q && apt-get install -yq python3-venv xvfb libgtk-3-0 libx11-xcb1 libasound2 libdbus-glib-1-2 >/dev/null
python3 -m venv /opt/venv && /opt/venv/bin/pip -q install "camoufox[geoip]==0.5.9" playwright==1.62.0 && /opt/venv/bin/python -m camoufox fetch >/dev/null
mkdir -p /opt/ph/out; touch /opt/ph/installed; fi
mkdir -p /opt/ph/reuse && cd /opt/ph/reuse && (gcloud storage cp -q "$B/_code/reuse.tgz" . 2>/dev/null || gsutil -q cp "$B/_code/reuse.tgz" .) && tar xzf reuse.tgz
systemctl stop phsuper 2>/dev/null; systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse /bin/bash -c "bash /opt/ph/reuse/supervisor.sh >> /opt/ph/reuse/supervisor.log 2>&1"
