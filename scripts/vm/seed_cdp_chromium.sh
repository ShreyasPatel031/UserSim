#!/usr/bin/env bash
# Foreground headed Chromium for the MCP engine's seed_vm backend (run by usersim-seed-cdp.service).
#
# CDP listens on the seed's loopback only (127.0.0.1:9222). The MCP server reaches it through an IAP SSH tunnel
# (mvp/deploy/usersim-seed-tunnel@.service); the seed VPC only admits IAP SSH (35.235.240.0/20 -> tcp:22), so CDP is
# never reachable from the internet. Each simulated user gets its own browser context inside this one Chromium.
set -euo pipefail
export DISPLAY="${DISPLAY:-:99}"
CDP_PORT="${MVP_WARM_CDP_PORT:-9222}"
SEED_ID="$(curl -sf -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/attributes/seed-id || hostname)"
IDENTITY="/var/lib/usersim-seed/${SEED_ID}"
PROFILE_DIR="${MVP_WARM_CHROME_PROFILE:-${IDENTITY}/profiles/_mcp_engine}"
[[ -d "$IDENTITY" ]] || PROFILE_DIR="$HOME/usersim/warm-chrome"
mkdir -p "$PROFILE_DIR"

if ! pgrep -f "Xvfb ${DISPLAY}" >/dev/null 2>&1; then
  Xvfb "$DISPLAY" -screen 0 1440x900x24 -nolisten tcp >/dev/null 2>&1 &
  sleep 0.5
fi

CHROME="$(find "$HOME/.cache/ms-playwright" -path '*/chrome-linux*/chrome' -type f 2>/dev/null | sort | tail -1 || true)"
if [[ -z "$CHROME" || ! -x "$CHROME" ]]; then
  echo "no chromium binary under $HOME/.cache/ms-playwright (run seed_provision.sh)" >&2
  exit 1
fi

rm -f "$PROFILE_DIR"/Singleton{Lock,Cookie,Socket}
exec "$CHROME" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$CDP_PORT" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run --no-default-browser-check \
  --disable-dev-shm-usage --disable-gpu \
  --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows \
  --window-size=1440,900 \
  about:blank
