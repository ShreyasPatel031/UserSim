#!/usr/bin/env bash
# 5×5×3 UI e2e: click Run, hide Ready while running, 75 flash-lite YESes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -f secrets/sa.json ]]; then
  export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-$ROOT/secrets/sa.json}"
fi
export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src:$ROOT"
export E2E_BASE="${1:-${E2E_BASE:-https://usersim.vercel.app}}"
python3 -m playwright install chromium >/dev/null 2>&1 || true
echo "→ e2e2 5×5×3 base=${E2E_BASE} judge=${E2E_JUDGE_MODEL:-gemini-2.5-flash-lite}"
exec python3 mvp/e2e2_matrix.py --base "$E2E_BASE" "${@:2}"
