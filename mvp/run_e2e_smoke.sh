#!/usr/bin/env bash
# STRICT local smoke e2e (1 user × 1 task). Fails on stuck cookie walls / no live / dead step nav.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f secrets/sa.json ]]; then
  export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-$ROOT/secrets/sa.json}"
fi

export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src:$ROOT"
export E2E_BASE="${1:-${E2E_BASE:-http://127.0.0.1:3000}}"
export E2E_SMOKE_OUT="${E2E_SMOKE_OUT:-$ROOT/results/e2e_smoke_local}"

python3 -m playwright install chromium >/dev/null 2>&1 || true

echo "→ STRICT smoke e2e base=${E2E_BASE} judge=${E2E_JUDGE_MODEL:-gemini-2.5-flash-lite}"
exec python3 mvp/e2e_smoke_local.py --base "$E2E_BASE" "${@:2}"
