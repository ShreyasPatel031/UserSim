#!/usr/bin/env bash
# Local test server — same behavior as Vercel production (VERCEL=1, sync POST, snapshot agents).
# Note: `vercel dev`'s local @vercel/fun runtime cannot run FastAPI/Mangum on this machine.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "${ROOT}/mvp/run_vercel_dev.sh"
