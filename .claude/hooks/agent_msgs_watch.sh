#!/usr/bin/env bash
# asyncRewake hook: waits for Grok->Claude Pub/Sub messages and WAKES this
# Claude Code session the moment one arrives (exit 2 => message shown to Claude
# as a system reminder, even when the session is idle). Re-armed by Stop hook.
# Agent name: $CLAUDE_AGENT_NAME or first line of ~/.claude_agent_name.
set -uo pipefail
cat >/dev/null 2>&1 || true   # drain hook JSON on stdin
A="${CLAUDE_AGENT_NAME:-$(head -1 "$HOME/.claude_agent_name" 2>/dev/null)}"
[ -n "$A" ] || exit 0
command -v gcloud >/dev/null || exit 0
LOCK="/tmp/agent_msgs_watch.$A.pid"
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then exit 0; fi  # one watcher only
echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT
SUB="projects/project-amer-scs-sandbox/subscriptions/claude-$A"
END=$(( $(date +%s) + ${AGENT_MSGS_WATCH_SECS:-3300} ))
while [ "$(date +%s)" -lt "$END" ]; do
  OUT=$(gcloud pubsub subscriptions pull "$SUB" --auto-ack --limit=20 \
    --format='value(message.attributes.ts,message.attributes.from,message.data)' 2>/dev/null)
  if [ -n "$OUT" ]; then
    { echo "New message(s) from Grok bots for agent '$A' (via Pub/Sub agent-msgs):"
      printf '%s\n' "$OUT" | sed 's/^/- /'
      echo "Reply instantly with: bash ping_grokbot.sh $A <session_url> fyi \"<reply>\""; } >&2
    exit 2
  fi
  sleep "${AGENT_MSGS_POLL_SECS:-3}"
done
exit 0
