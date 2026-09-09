#!/usr/bin/env bash
# 3-site UI e2e: loading email box, then report arrow, then real /report pages.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f secrets/sa.json ]]; then
  export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-$ROOT/secrets/sa.json}"
fi

export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src:$ROOT"
export E2E_BASE="${1:-${E2E_BASE:-https://usersim.vercel.app}}"
export E2E_THREE_OUT="${E2E_THREE_OUT:-$ROOT/results/e2e_three_reports}"

python3 -m playwright install chromium >/dev/null 2>&1 || true

echo "→ three-site report e2e base=${E2E_BASE}"
exec python3 mvp/e2e_three_reports.py --base "$E2E_BASE" "${@:2}"
