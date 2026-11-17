#!/usr/bin/env bash
# Install / restart the engine Chromium on a signup seed. Run ON the seed (as the user that ran seed_provision.sh):
#   gcloud compute ssh usersim-signup-seed-N --zone=us-central1-a --tunnel-through-iap \
#     --command='bash ~/usersim/scripts/vm/install_seed_cdp.sh'
#
# Installs, idempotently:
#   1. AppArmor profile usersim-seed-chrome: Ubuntu 24.04 restricts unprivileged user namespaces, so Playwright's
#      Chromium dies with "No usable sandbox". The profile grants `userns` to that binary only; the sandbox stays on.
#   2. sshd keepalive (ClientAliveInterval 15 / CountMax 2): a dropped IAP tunnel otherwise leaves a half-open CDP
#      client attached, and Chromium then holds every new page waiting for that dead debugger (Nov 17, seed 0).
#   3. usersim-seed-cdp.service: headed Chromium, CDP on 127.0.0.1:9222 only.
#   4. usersim-seed-cdp-watchdog.timer: every minute, as root, opens a fresh context and loads a data: URL through
#      local CDP (mvp/sim_mcp/seed_probe.py); two failures in a row restart usersim-seed-cdp.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
U="$(id -un)"
H="$HOME"
REPO="$H/usersim"
PY="$REPO/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"
# The probe needs websockets>=13 (sync client); without it the watchdog would restart Chromium every 2 minutes.
if ! "$PY" -c 'import websockets.sync.client' 2>/dev/null; then
  if [[ -x "$REPO/.venv/bin/python" ]] && command -v uv >/dev/null 2>&1; then
    (cd "$REPO" && uv pip install -q --python "$REPO/.venv/bin/python" 'websockets>=13')
  else
    "$PY" -m pip install -q 'websockets>=13'
  fi
  "$PY" -c 'import websockets.sync.client' || { echo "FATAL: websockets sync client missing for $PY" >&2; exit 1; }
fi

# ---- 1. AppArmor: userns for Playwright's Chromium only ----------------------
if [[ -d /etc/apparmor.d ]]; then
  sudo tee /etc/apparmor.d/usersim-seed-chrome >/dev/null <<'AA'
# UserSim seed: let Playwright's Chromium create user namespaces for its sandbox (Ubuntu 24.04 restricts them).
abi <abi/4.0>,
include <tunables/global>

profile usersim-seed-chrome /home/*/.cache/ms-playwright/chromium-*/chrome-linux*/chrome flags=(unconfined) {
  userns,
  include if exists <local/usersim-seed-chrome>
}
AA
  if command -v apparmor_parser >/dev/null 2>&1; then
    sudo apparmor_parser -r /etc/apparmor.d/usersim-seed-chrome
    echo "apparmor: usersim-seed-chrome loaded"
  fi
fi

# ---- 2. sshd keepalive: half-open tunnel clients die in ~30 s ----------------
sudo install -d /etc/ssh/sshd_config.d
printf 'ClientAliveInterval 15\nClientAliveCountMax 2\n' | sudo tee /etc/ssh/sshd_config.d/60-usersim-keepalive.conf >/dev/null
sudo sshd -t && (sudo systemctl reload ssh 2>/dev/null || sudo systemctl reload sshd 2>/dev/null || true)
echo "sshd: keepalive 15s x2"

# ---- 3. Chromium service ------------------------------------------------------
sudo tee /etc/systemd/system/usersim-seed-cdp.service >/dev/null <<UNIT
[Unit]
Description=UserSim seed Chromium (CDP on 127.0.0.1:9222 for the MCP engine)
After=network-online.target
Wants=network-online.target

[Service]
User=${U}
Environment=HOME=${H}
Environment=DISPLAY=:99
ExecStart=/bin/bash ${REPO}/scripts/vm/seed_cdp_chromium.sh
Restart=always
RestartSec=5
KillMode=control-group

[Install]
WantedBy=multi-user.target
UNIT

# ---- 4. watchdog: local deep probe every minute, restart on 2 failures --------
sudo tee /usr/local/bin/usersim-seed-cdp-watchdog >/dev/null <<WD
#!/usr/bin/env bash
# Restart usersim-seed-cdp when Chromium is up but wedged (pages never load). Installed by install_seed_cdp.sh.
set -u
STATE=/run/usersim-seed-cdp-watchdog.fails
systemctl is-active --quiet usersim-seed-cdp || exit 0   # systemd already restarts a dead service
if out=\$(timeout 25 "${PY}" "${REPO}/mvp/sim_mcp/seed_probe.py" http://127.0.0.1:9222 2>&1); then
  rm -f "\$STATE"; exit 0
fi
n=\$(( \$(cat "\$STATE" 2>/dev/null || echo 0) + 1 )); echo "\$n" > "\$STATE"
logger -t usersim-seed-cdp-watchdog "probe failed (\$n): \$out"
if (( n >= 2 )); then
  logger -t usersim-seed-cdp-watchdog "restarting usersim-seed-cdp"
  rm -f "\$STATE"; systemctl restart usersim-seed-cdp
fi
WD
sudo chmod 0755 /usr/local/bin/usersim-seed-cdp-watchdog
sudo tee /etc/systemd/system/usersim-seed-cdp-watchdog.service >/dev/null <<'UNIT'
[Unit]
Description=UserSim seed Chromium wedge probe

[Service]
Type=oneshot
ExecStart=/usr/local/bin/usersim-seed-cdp-watchdog
UNIT
sudo tee /etc/systemd/system/usersim-seed-cdp-watchdog.timer >/dev/null <<'UNIT'
[Unit]
Description=Probe the seed Chromium every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=5s

[Install]
WantedBy=timers.target
UNIT

# The warm-chrome helper from older runs would hold :9222.
pkill -f 'remote-debugging-port=9222' || true
sudo systemctl daemon-reload
sudo systemctl enable --now usersim-seed-cdp.service usersim-seed-cdp-watchdog.timer
sudo systemctl restart usersim-seed-cdp.service
for _ in $(seq 1 30); do
  if "$PY" "$REPO/mvp/sim_mcp/seed_probe.py" http://127.0.0.1:9222 >/dev/null 2>&1; then
    echo "SEED_CDP_OK $(curl -sf http://127.0.0.1:9222/json/version | python3 -c 'import json,sys;print(json.load(sys.stdin)["Browser"])')"
    ss -ltn 'sport = :9222'
    exit 0
  fi
  sleep 1
done
echo "SEED_CDP_FAIL" >&2; journalctl -u usersim-seed-cdp -n 30 --no-pager >&2; exit 1
