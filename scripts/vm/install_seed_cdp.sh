#!/usr/bin/env bash
# Install / restart the engine Chromium on a signup seed. Run ON the seed (as the user that ran seed_provision.sh):
#   gcloud compute ssh usersim-signup-seed-N --zone=us-central1-a --tunnel-through-iap \
#     --command='bash ~/usersim/scripts/vm/install_seed_cdp.sh'
set -euo pipefail
U="$(id -un)"
H="$HOME"
sudo tee /etc/systemd/system/usersim-seed-cdp.service >/dev/null <<UNIT
[Unit]
Description=UserSim seed Chromium (CDP on 127.0.0.1:9222 for the MCP engine)
After=network-online.target
Wants=network-online.target

[Service]
User=${U}
Environment=HOME=${H}
Environment=DISPLAY=:99
ExecStart=/bin/bash ${H}/usersim/scripts/vm/seed_cdp_chromium.sh
Restart=always
RestartSec=5
KillMode=control-group

[Install]
WantedBy=multi-user.target
UNIT
# The warm-chrome helper from older runs would hold :9222.
pkill -f 'remote-debugging-port=9222' || true
sudo systemctl daemon-reload
sudo systemctl enable --now usersim-seed-cdp.service
sudo systemctl restart usersim-seed-cdp.service
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:9222/json/version >/dev/null; then
    echo "SEED_CDP_OK $(curl -sf http://127.0.0.1:9222/json/version | python3 -c 'import json,sys;print(json.load(sys.stdin)["Browser"])')"
    ss -ltn 'sport = :9222'
    exit 0
  fi
  sleep 1
done
echo "SEED_CDP_FAIL" >&2; journalctl -u usersim-seed-cdp -n 30 --no-pager >&2; exit 1
