#!/usr/bin/env bash
# Install (or update) the fetch gateway on the VM. Run from a checkout, as root:
#   sudo bash src/fetchgate/deploy/install_vm.sh                 # code, user, service, client setup
#   sudo bash src/fetchgate/deploy/install_vm.sh --import-creds  # also copy the residential proxy and Apify token
#                                                               # from the app's saved keys into the gateway's file
#   sudo bash src/fetchgate/deploy/install_vm.sh --strip-agent   # also delete ~agent/php/proxy.txt
# Never prints a credential. Ask the founder before --import-creds or --strip-agent (AGENTS.md).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"               # .../src/fetchgate
VENV_PY=/opt/usersim/venv/bin/python
CREDS=/etc/fetchgate/credentials.env
APP_KEYS=/var/lib/usersim/discovery_keys.json
log() { echo "[fetchgate-install] $*"; }

id fetchgate >/dev/null 2>&1 || useradd --system --home-dir /var/lib/fetchgate --create-home --shell /usr/sbin/nologin fetchgate
install -d -o root -g root -m 755 /opt/fetchgate /opt/fetchgate/src
rsync -a --delete --exclude '__pycache__' --exclude 'test_*.py' "$SRC/" /opt/fetchgate/src/fetchgate/
chown -R root:root /opt/fetchgate && chmod -R go-w /opt/fetchgate
install -d -o fetchgate -g fetchgate -m 700 /etc/fetchgate /var/lib/fetchgate
install -d -o fetchgate -g fetchgate -m 755 /var/log/fetchgate   # the spend log has no secrets: anyone may read it
touch /var/log/fetchgate/fetches.jsonl && chown fetchgate:fetchgate /var/log/fetchgate/fetches.jsonl
chmod 644 /var/log/fetchgate/fetches.jsonl   # the service and the app (root) append; agents can only read
[ -f "$CREDS" ] || install -o fetchgate -g fetchgate -m 600 /dev/null "$CREDS"

if [ "${1:-}" = "--import-creds" ] || [ "${2:-}" = "--import-creds" ]; then
  python3 - "$APP_KEYS" "$CREDS" <<'PY'
import json, os, sys
keys, dest = sys.argv[1], sys.argv[2]
saved = json.load(open(keys))
have = {l.split("=", 1)[0] for l in open(dest) if "=" in l}
add = [f"{k}={saved[k]}" for k in ("PROXY_URL", "APIFY_TOKEN") if saved.get(k) and k not in have]
with open(dest, "a") as f:
    f.write("".join(x + "\n" for x in add))
print("[fetchgate-install] imported:", [x.split("=", 1)[0] for x in add] or "nothing new")
PY
  chown fetchgate:fetchgate "$CREDS"; chmod 600 "$CREDS"
fi

if [ "${1:-}" = "--strip-agent" ] || [ "${2:-}" = "--strip-agent" ]; then
  for f in /home/agent/php/proxy.txt; do [ -e "$f" ] && shred -u "$f" && log "removed $f"; done
fi

# Camoufox's browser for the fetchgate user (its own HOME); needs Firefox's system libraries (already on the VM).
sudo -u fetchgate HOME=/var/lib/fetchgate "$VENV_PY" -m camoufox fetch >/dev/null 2>&1 || log "camoufox fetch failed (browser routes off)"
sudo -u fetchgate HOME=/var/lib/fetchgate "$VENV_PY" -m playwright install chromium >/dev/null 2>&1 || log "chromium install failed"

install -m 644 "$SRC/deploy/fetchgate.service" /etc/systemd/system/fetchgate.service
systemctl daemon-reload
systemctl enable fetchgate.service >/dev/null
systemctl restart fetchgate.service

# Client side: every login and `ssh vm '<cmd>'` gets FETCHGATE_URL (pam_env), and both Pythons can import fetchgate.
grep -q '^FETCHGATE_URL=' /etc/environment || echo 'FETCHGATE_URL=http://127.0.0.1:8765' >> /etc/environment
for sp in /usr/lib/python3/dist-packages "$($VENV_PY -c 'import site;print(site.getsitepackages()[0])')"; do
  echo /opt/fetchgate/src > "$sp/fetchgate.pth"
done

sleep 2
curl -sf http://127.0.0.1:8765/health && echo && log "fetchgate is up"
