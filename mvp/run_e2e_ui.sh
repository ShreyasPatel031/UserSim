#!/usr/bin/env bash
# Real UI e2e against prod (or local): click Run, not Smoke.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f secrets/sa.json ]]; then
  export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-$ROOT/secrets/sa.json}"
fi

export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src:$ROOT"
export E2E_BASE="${1:-${E2E_BASE:-https://usersim.vercel.app}}"

# Ensure Chromium is available for Playwright.
python3 -m playwright install chromium >/dev/null 2>&1 || true

echo "→ UI e2e base=${E2E_BASE} judge=${E2E_JUDGE_MODEL:-gemini-2.5-flash-lite}"
exec python3 mvp/e2e_ui_run.py --base "$E2E_BASE" "${@:2}"
