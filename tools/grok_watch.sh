#!/usr/bin/env bash
# Single-instance watcher: every 15 s, list Grok Bot's mailbox (from_grokbot/, to_claude/) and append each NEW
# non-status file (name, time, first 2,000 chars) as one JSON line to the local inbox. Never prints secrets.
INBOX_DIR=${GROK_INBOX_DIR:-/root/.usersim/grok_inbox}; mkdir -p "$INBOX_DIR"
exec 9>"$INBOX_DIR/watch.lock"; flock -n 9 || exit 0
B=gs://usersim-bakeoff-347838016394/usersim_sim/mailbox
SKIP='status\.md|feeds-gaps|progress\.json|GCP_BUDGET|budget_history|hn-minute-gaps|recorder-cutover|wayback_status\.reply|vote_series|NEEDS_HUMAN|RELAY_log|TOTAL:'
snap() { { gsutil ls -l "$B/from_grokbot/" 2>/dev/null; gsutil ls -l "$B/to_claude/" 2>/dev/null; } | grep -v -E "$SKIP" | awk 'NF>=3{print $2" "$3}' | sort; }
[ -f "$INBOX_DIR/seen.txt" ] || snap > "$INBOX_DIR/seen.txt"
while true; do
  snap > "$INBOX_DIR/now.txt"
  comm -13 "$INBOX_DIR/seen.txt" "$INBOX_DIR/now.txt" | while read -r ts url; do
    # A file that is merely rewritten (e.g. an auto-regenerated in-progress reply) is delivered at most once per hour.
    now_s=$(date +%s); last=$(awk -v u="$url" '$2==u{t=$1} END{print t+0}' "$INBOX_DIR/delivered.txt" 2>/dev/null)
    [ $((now_s - ${last:-0})) -lt 3600 ] && continue
    echo "$now_s $url" >> "$INBOX_DIR/delivered.txt"
    body=$(gsutil cat "$url" 2>/dev/null | head -c 2000)
    python3 -I -c 'import json,sys; print(json.dumps({"ts":sys.argv[1],"url":sys.argv[2],"body":sys.argv[3]}))' "$ts" "$url" "$body" >> "$INBOX_DIR/inbox.jsonl"
  done
  mv "$INBOX_DIR/now.txt" "$INBOX_DIR/seen.txt"
  sleep 15
done
