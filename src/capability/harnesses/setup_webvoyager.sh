#!/usr/bin/env bash
# Set up upstream WebVoyager in an isolated venv.
#
# WebVoyager pins openai==1.1.1 / selenium==4.15.2. Newer versions work and are
# needed for a current Chrome, so deps are installed explicitly rather than from
# its requirements.txt.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
VENDOR="$ROOT/vendor/WebVoyager"
VENV="$ROOT/.venv-webvoyager"

if [ ! -d "$VENDOR" ]; then
  mkdir -p "$ROOT/vendor"
  git clone --depth 1 https://github.com/MinorJerry/WebVoyager.git "$VENDOR"
fi

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install "openai>=1.40" "selenium>=4.20" "pillow>=10"

# Selenium locates the browser by name; reuse the Playwright Chromium already
# on disk instead of installing a second Chrome.
CHROME="$(ls -d "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux64/chrome 2>/dev/null | head -1 || true)"
if [ -n "$CHROME" ] && ! command -v google-chrome >/dev/null 2>&1; then
  ln -sf "$CHROME" /usr/local/bin/google-chrome
fi

echo "WebVoyager venv ready: $VENV"
