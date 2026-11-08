#!/usr/bin/env bash
# Pull fleet-cursor replies from agent-msgs (non-destructive peek: nack by not acking in pull --auto-ack=false).
set -euo pipefail
PROJECT="${AGENT_MSGS_PROJECT:?set AGENT_MSGS_PROJECT for agent-msgs Pub/Sub}"
SUB="${AGENT_MSGS_SUB:-fleet-cursor}"
LIMIT="${1:-5}"
gcloud pubsub subscriptions pull "$SUB" \
  --project="$PROJECT" \
  --limit="$LIMIT" \
  --format='json' \
  --auto-ack="${AUTO_ACK:-false}"
