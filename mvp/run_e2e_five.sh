#!/usr/bin/env bash
# 5-thread e2e: personas + tasks + 1 competitor, flash-lite judges every PNG.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f secrets/sa.json ]]; then
  export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-$ROOT/secrets/sa.json}"
fi

export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src:$ROOT"
export E2E_BASE="${1:-${E2E_BASE:-https://usersim.vercel.app}}"
export E2E_FIVE_OUT="${E2E_FIVE_OUT:-$ROOT/results/e2e_five_threads}"

python3 -m playwright install chromium >/dev/null 2>&1 || true

echo "→ five-thread e2e base=${E2E_BASE} judge=${E2E_JUDGE_MODEL:-gemini-2.5-flash-lite}"
exec python3 mvp/e2e_five_threads.py --base "$E2E_BASE" "${@:2}"
