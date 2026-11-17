#!/usr/bin/env bash
# Install / restart the Camoufox Playwright server on a signup seed (limits.json browser_engine = "camoufox").
# Run ON the seed as the user that owns ~/usersim (install_seed_cdp.sh calls it; safe to rerun):
#   bash ~/usersim/scripts/vm/install_seed_camoufox.sh
#
# - camoufox==0.5.9 and playwright==1.62.0 in ~/usersim/.venv. The engine connects with playwright.firefox.connect,
#   and Playwright refuses a client/server version mismatch, so this pin must equal requirements.txt.
# - the Camoufox browser: `python -m camoufox fetch`, or, when GitHub's API refuses (403), the pinned release asset
#   downloaded directly into ~/usersim/camoufox-browser.
# - usersim-seed-camoufox.service: scripts/vm/seed_camoufox_server.py on 127.0.0.1:9333 (ws path /usersim) only,
#   on its own virtual display, one fixed fingerprint per seed (identity disk camoufox_preset.json).
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
U="$(id -un)"
H="$HOME"
REPO="$H/usersim"
PY="$REPO/.venv/bin/python"
PW_VERSION="${USERSIM_PLAYWRIGHT_VERSION:-$(grep -oP '^playwright==\K[0-9.]+' "$REPO/requirements.txt" 2>/dev/null || echo 1.62.0)}"
CAMOUFOX_VERSION="${USERSIM_CAMOUFOX_VERSION:-0.5.9}"
BROWSER_TAG="${USERSIM_CAMOUFOX_BROWSER_TAG:-v158.0.1-beta.41}"
BROWSER_DIR="$REPO/camoufox-browser"

echo "==> camoufox ${CAMOUFOX_VERSION} + playwright ${PW_VERSION}"
(cd "$REPO" && uv pip install -q --python "$PY" "camoufox==${CAMOUFOX_VERSION}" "playwright==${PW_VERSION}")

BIN=""
if "$PY" -m camoufox fetch >/tmp/camoufox_fetch.log 2>&1; then
  echo "    camoufox fetch ok"
else
  echo "    camoufox fetch failed ($(tail -1 /tmp/camoufox_fetch.log)); downloading ${BROWSER_TAG} directly"
  if [[ ! -x "$BROWSER_DIR/camoufox-bin" ]]; then
    ver="${BROWSER_TAG#v}"
    tmp="$(mktemp -d)"
    curl -fsSL -o "$tmp/cfx.zip" \
      "https://github.com/daijro/camoufox/releases/download/${BROWSER_TAG}/camoufox-${ver}-lin.x86_64.zip"
    mkdir -p "$BROWSER_DIR"
    "$PY" -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$tmp/cfx.zip" "$BROWSER_DIR"
    chmod +x "$BROWSER_DIR"/camoufox "$BROWSER_DIR"/camoufox-bin
    rm -rf "$tmp"
  fi
  BIN="$BROWSER_DIR/camoufox-bin"
fi

sudo tee /etc/systemd/system/usersim-seed-camoufox.service >/dev/null <<UNIT
[Unit]
Description=UserSim seed Camoufox Playwright server (ws://127.0.0.1:9333/usersim for the MCP engine)
After=network-online.target
Wants=network-online.target

[Service]
User=${U}
Environment=HOME=${H}
Environment=USERSIM_CAMOUFOX_BIN=${BIN}
ExecStart=${PY} ${REPO}/scripts/vm/seed_camoufox_server.py --port 9333 --ws-path usersim
Restart=always
RestartSec=5
KillMode=control-group

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now usersim-seed-camoufox.service
sudo systemctl restart usersim-seed-camoufox.service
for _ in $(seq 1 60); do
  if "$PY" "$REPO/mvp/sim_mcp/seed_probe.py" ws://127.0.0.1:9333/usersim 15 >/dev/null 2>&1; then
    echo "SEED_CAMOUFOX_OK $(ss -ltn 'sport = :9333' | tail -1)"
    exit 0
  fi
  sleep 2
done
echo "SEED_CAMOUFOX_FAIL" >&2; journalctl -u usersim-seed-camoufox -n 30 --no-pager >&2; exit 1
