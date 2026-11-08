#!/usr/bin/env bash
# Publish to agent-msgs with standard attributes (orchestrator, grokbot, fleet peers).
set -euo pipefail
PROJECT="${AGENT_MSGS_PROJECT:?set AGENT_MSGS_PROJECT for agent-msgs Pub/Sub}"
TOPIC="${AGENT_MSGS_TOPIC:-agent-msgs}"
TO="${1:-}"
FROM="${2:-fleet-cursor}"
shift 2 || true
MSG="${*:-}"
[[ -n "$TO" && -n "$MSG" ]] || {
  echo "usage: $0 <to> [from] message..." >&2
  echo "  to: orchestrator | grokbot | prediction | fleet-cursor | all" >&2
  exit 1
}
gcloud pubsub topics publish "$TOPIC" \
  --project="$PROJECT" \
  --message="$MSG" \
  --attribute="to=${TO},from=${FROM},ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
