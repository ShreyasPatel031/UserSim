#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../" && pwd)"
cd "$ROOT"
mkdir -p secrets/voice_ai_sessions
PYTHONPATH=src python3 scripts/voice_ai_auth/export_sessions.py "$@"
PYTHONPATH=src python3 scripts/voice_ai_auth/verify_dashboards.py 2>/dev/null || true
