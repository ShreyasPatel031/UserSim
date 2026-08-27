#!/usr/bin/env bash
# Open Retell + Vapi login in default Chrome (Google: shreyashfs@gmail.com).
set -euo pipefail
echo "Sign in with Google in each tab, then Cmd+Q Chrome and run:"
echo "  ./scripts/voice_ai_auth/save_sessions.sh --only retell,vapi"
open -a "Google Chrome" "https://dashboard.retellai.com/login"
sleep 1
open -a "Google Chrome" "https://dashboard.vapi.ai/login"
