#!/usr/bin/env bash
# Install systemd timer that polls Spot VMs and restarts TERMINATED ones.
set -euo pipefail

install -d -m 0755 /opt/usersim_fm/scripts /var/lib/usersim-spot-watch
install -m 0755 /tmp/spot_watchdog.py /opt/usersim_fm/scripts/spot_watchdog.py

# Ensure gcloud exists (COS/debian images vary).
if ! command -v gcloud >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y apt-transport-https ca-certificates gnupg curl python3
  curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    >/etc/apt/sources.list.d/google-cloud-sdk.list
  apt-get update -y
  apt-get install -y google-cloud-cli
fi

cat >/etc/systemd/system/usersim-spot-watchdog.service <<'EOF'
[Unit]
Description=UserSim Spot watchdog (one poll)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
Environment=STATE_DIR=/var/lib/usersim-spot-watch
Environment=WATCH_LOG=/var/log/usersim-spot-watch.log
Environment=WATCH_LABEL_KEY=usersim-spot-watch
Environment=WATCH_LABEL_VALUE=true
# ADC: this VM's service account (needs compute.instances.start + list)
ExecStart=/usr/bin/python3 -u /opt/usersim_fm/scripts/spot_watchdog.py
Nice=10
EOF

cat >/etc/systemd/system/usersim-spot-watchdog.timer <<'EOF'
[Unit]
Description=Poll Spot VMs every minute; restart if preempted

[Timer]
OnBootSec=30
OnUnitActiveSec=60
AccuracySec=10
Unit=usersim-spot-watchdog.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now usersim-spot-watchdog.timer
systemctl start usersim-spot-watchdog.service || true
systemctl status usersim-spot-watchdog.timer --no-pager || true
echo INSTALLED_SPOT_WATCHDOG
