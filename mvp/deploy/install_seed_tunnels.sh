#!/usr/bin/env bash
# On the MCP server host (usersim-grokbot-web): one IAP SSH tunnel per seed, so the engine's seed_vm backend reaches
# each seed's CDP at 127.0.0.1:1922N without any seed port being open to the internet.
#   sudo SEEDS="0 1 2" bash mvp/deploy/install_seed_tunnels.sh
# Needs the VM's service account to hold roles/iap.tunnelResourceAccessor and SSH to the seeds (OS Login or
# compute.instanceAdmin.v1 for metadata keys). Then list the ports in limits.json seed_cdp_endpoints.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SEEDS="${SEEDS:-0}"
install -m 0644 "$SCRIPT_DIR/usersim-seed-tunnel@.service" /etc/systemd/system/usersim-seed-tunnel@.service
systemctl daemon-reload
for n in $SEEDS; do
  systemctl enable --now "usersim-seed-tunnel@${n}.service"
  systemctl restart "usersim-seed-tunnel@${n}.service"
done
sleep 8
for n in $SEEDS; do
  if curl -sf "http://127.0.0.1:1922${n}/json/version" >/dev/null; then echo "seed-${n} CDP ok on 127.0.0.1:1922${n}"
  else echo "seed-${n} CDP NOT reachable"; journalctl -u "usersim-seed-tunnel@${n}" -n 15 --no-pager; fi
done
