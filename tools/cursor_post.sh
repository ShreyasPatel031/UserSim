#!/usr/bin/env bash
# POST a message to the Cursor extraction agent's webhook (same mechanism as tools/grokbot_post.sh).
# Credentials live OUTSIDE the repo: /root/.usersim/cursor_extract_webhook.env (CURSOR_WEBHOOK_URL, CURSOR_WEBHOOK_KEY),
# copied from gs://.../usersim_sim/secrets/cursor_extract_webhook.env. Never print or commit them. Usage:
#   tools/cursor_post.sh <from_agent> <topic> <details> [session_url]
set -euo pipefail
ENV=${CURSOR_WEBHOOK_ENV:-/root/.usersim/cursor_extract_webhook.env}
if [ ! -r "$ENV" ]; then
  gsutil -q cp gs://usersim-bakeoff-347838016394/usersim_sim/secrets/cursor_extract_webhook.env "$ENV" 2>/dev/null && chmod 600 "$ENV" || { echo "no credentials at $ENV (ask Shreyas to save secrets/cursor_extract_webhook.env)" >&2; exit 2; }
fi
set -a; . "$ENV"; set +a
from=$1; topic=$2; details=$3; session=${4:-}
payload=$(python3 -I -c 'import json,sys,datetime; a,n,d,s=sys.argv[1:5]; print(json.dumps({"agent":a,"need":n,"details":d,"session_url":s,"ts_utc":datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}))' "$from" "$topic" "$details" "$session")
code=$(curl -sS -o /tmp/cursor_post_resp.$$ -w '%{http_code}' -X POST "$CURSOR_WEBHOOK_URL" -H "Authorization: Bearer $CURSOR_WEBHOOK_KEY" -H 'Content-Type: application/json' --data "$payload")
echo "HTTP $code $(head -c 200 /tmp/cursor_post_resp.$$ | sed 's/crsr_[A-Za-z0-9]*/[key]/g')"; rm -f /tmp/cursor_post_resp.$$
[ "$code" = 200 ]
