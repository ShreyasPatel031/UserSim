#!/usr/bin/env bash
set -euo pipefail
SLOT="${1:-32}"
VENV="/Users/shreyaspatel/.gemini/antigravity/brain/9180c5fc-4f89-4408-aad0-3184e5de8475/scratch/.camoufox_venv"
SCRIPT="/Users/shreyaspatel/.gemini/antigravity/scratch/UserSim/usersim_core/fleet/local_signin_sync.py"
exec "$VENV/bin/python" "$SCRIPT" --slot "$SLOT"
