#!/usr/bin/env bash
# DEPRECATED for Google login — use open_auth_chrome.sh then save_sessions.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../" && pwd)"
cd "$ROOT"
exec "$ROOT/scripts/voice_ai_auth/open_auth_chrome.sh"
