#!/usr/bin/env bash
# Fast smoke test: health check + async study with poll (fail early on timeout).
set -euo pipefail

BASE="${1:-http://127.0.0.1:8787}"
TIMEOUT_S="${SMOKE_TIMEOUT_S:-60}"
POLL_S="${SMOKE_POLL_S:-2}"
URL="${SMOKE_URL:-https://useagency.dev/}"
SEGMENT="${SMOKE_SEGMENT:-Startup founders evaluating AI infrastructure tools}"

health_only=false
[[ "${2:-}" == "--health-only" ]] && health_only=true

echo "→ health ${BASE}/health"
curl -sf --max-time 5 "${BASE}/health" | head -c 200
echo ""

if $health_only; then
  echo "OK health"
  exit 0
fi

echo "→ POST study (async; poll up to ${TIMEOUT_S}s)"
start_json=$(curl -sf --max-time 10 -X POST "${BASE}/api/studies" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"${URL}\",\"segment\":\"${SEGMENT}\"}")

# Vercel sync mode returns full study; local async returns study_id
if echo "$start_json" | grep -q '"study_id"'; then
  study_id=$(echo "$start_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['study_id'])")
  echo "  study_id=${study_id}"
  elapsed=0
  while (( elapsed < TIMEOUT_S )); do
    body=$(curl -sf --max-time 10 "${BASE}/api/studies/${study_id}")
    status=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
    phase=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('phase',''))")
    echo "  [${elapsed}s] status=${status} phase=${phase}"
    if [[ "$status" == "complete" ]]; then
      echo "OK study complete in ~${elapsed}s"
      exit 0
    fi
    if [[ "$status" == "error" ]]; then
      echo "FAIL study error:"
      echo "$body" | python3 -m json.tool 2>/dev/null || echo "$body"
      exit 1
    fi
    sleep "$POLL_S"
    elapsed=$((elapsed + POLL_S))
  done
  echo "FAIL timeout after ${TIMEOUT_S}s (still ${status:-running})"
  exit 1
fi

status=$(echo "$start_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
if [[ "$status" == "complete" ]]; then
  echo "OK study complete (sync response)"
  exit 0
fi
echo "FAIL unexpected sync response:"
echo "$start_json" | python3 -m json.tool 2>/dev/null || echo "$start_json"
exit 1
