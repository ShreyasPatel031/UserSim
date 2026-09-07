#!/usr/bin/env bash
# Keep a headed Chromium alive on the seed with CDP :9222 for instant navigate/screenshot.
set -euo pipefail
export HOME="${HOME:-/home/shreyaspatel}"
export DISPLAY="${DISPLAY:-:99}"
CDP_PORT="${MVP_WARM_CDP_PORT:-9222}"
CDP_URL="http://127.0.0.1:${CDP_PORT}"
PROFILE_DIR="${MVP_WARM_CHROME_PROFILE:-$HOME/usersim/warm-chrome}"
LOG="${HOME}/usersim/warm-chrome.log"

if curl -sf "${CDP_URL}/json/version" >/dev/null 2>&1; then
  echo "WARM_CDP_OK ${CDP_URL}"
  exit 0
fi

if ! pgrep -f "Xvfb ${DISPLAY}" >/dev/null 2>&1; then
  Xvfb "$DISPLAY" -screen 0 1440x900x24 >"$HOME/usersim/xvfb.log" 2>&1 &
  sleep 0.5
fi

CHROME=""
# Avoid sync_playwright (noisy); prefer cached binary path.
CHROME="$(find "$HOME/.cache/ms-playwright" /root/.cache/ms-playwright -path '*/chrome-linux*/chrome' -type f 2>/dev/null | head -1 || true)"
if [[ -z "$CHROME" || ! -x "$CHROME" ]]; then
  if [[ -x "$HOME/usersim/.venv/bin/python" ]]; then
    CHROME="$("$HOME/usersim/.venv/bin/python" -c 'from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()' 2>/dev/null || true)"
  fi
fi
if [[ -z "$CHROME" || ! -x "$CHROME" ]]; then
  echo "WARM_CDP_FAIL no chromium binary" >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"
nohup "$CHROME" \
  --remote-debugging-port="$CDP_PORT" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --window-size=1440,900 \
  about:blank \
  >>"$LOG" 2>&1 &
echo "WARM_CDP_START pid=$!"

for _ in $(seq 1 50); do
  if curl -sf "${CDP_URL}/json/version" >/dev/null 2>&1; then
    echo "WARM_CDP_OK ${CDP_URL}"
    exit 0
  fi
  sleep 0.1
done
echo "WARM_CDP_FAIL timeout" >&2
exit 1
