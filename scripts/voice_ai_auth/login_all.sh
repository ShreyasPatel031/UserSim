#!/usr/bin/env bash
# Open Chrome and walk through voice-AI dashboard logins (Google: shreyashfs@gmail.com).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../" && pwd)"
cd "$ROOT"
mkdir -p secrets/voice_ai_sessions secrets/voice_ai_browser_profile
echo "==> Voice AI dashboard login"
echo "    Email: shreyashfs@gmail.com (Sign in with Google on each site)"
echo ""
PYTHONPATH=src python3 scripts/voice_ai_auth/login_dashboards.py "$@"
