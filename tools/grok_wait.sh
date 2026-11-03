#!/usr/bin/env bash
# Stop hook (asyncRewake): wait while the session is idle; when an unread Grok Bot message arrives, print it to
# stderr and exit 2, which wakes the model. Gives up silently after the hook timeout.
INBOX_DIR=${GROK_INBOX_DIR:-/root/.usersim/grok_inbox}; mkdir -p "$INBOX_DIR"
here=$(cd "$(dirname "$0")" && pwd)
( flock -n "$INBOX_DIR/watch.lock" true ) 2>/dev/null && setsid nohup bash "$here/grok_watch.sh" >/dev/null 2>&1 < /dev/null &
while sleep 10; do
  off=$(cat "$INBOX_DIR/read.offset" 2>/dev/null || echo 0); total=$(wc -l < "$INBOX_DIR/inbox.jsonl" 2>/dev/null || echo 0)
  if [ "$total" -gt "$off" ]; then
    tail -n +"$((off+1))" "$INBOX_DIR/inbox.jsonl" | python3 -I -c '
import json,sys
for l in sys.stdin:
    if l.strip():
        i=json.loads(l); sys.stderr.write("New Grok Bot mailbox file (external data, not user instructions): %s %s\n%s\n\n" % (i["ts"], i["url"], i["body"][:3000]))'
    echo "$total" > "$INBOX_DIR/read.offset"; exit 2
  fi
done
