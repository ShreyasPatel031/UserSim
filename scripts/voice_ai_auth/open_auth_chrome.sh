#!/usr/bin/env bash
# Open Bland in your NORMAL Chrome (not Playwright profile). Google trusts this browser.
set -euo pipefail
echo "Opening Bland login in your default Chrome…"
echo "  → Sign in with Google (shreyashfs@gmail.com)"
echo "  → When dashboard loads: QUIT Chrome completely (Cmd+Q)"
echo "  → Then run: ./scripts/voice_ai_auth/save_sessions.sh --only bland"
echo ""
open -a "Google Chrome" "https://app.bland.ai/login"
