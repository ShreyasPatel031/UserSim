#!/bin/bash
# Fleet primary for the 15-min PH API live snapshot (Data Feeder box api_loop stays as standby).
# Runs on the live slot VM (FLEET_LIVE_SLOTS, default 39) as systemd unit phlive, in place of pdeep.
# Code: gs://.../raw/ph_at_launch/live/tools/api_loop/ (box copy). Token: Secret Manager PH_API_TOKEN; waits until it exists.
# Dedupe: one file per planned slot, <day>/snapshots/<YYYYMMDDTHHMM>PT_api.jsonl; whoever writes it first wins (api_snap cp -n).
# This loop stats the planned file before fetching and skips the slot if it already exists, so a late writer spends no API budget.
# No api_split / precut here: the box keeps those.
set -u
B="${PH_GCS_ROOT:-gs://${MVP_GCS_BUCKET:?}/usersim_sim}"; T="$B/raw/ph_at_launch/live/tools/api_loop"
W=/workspace; L=$W/phlaunch/live; S=$L/state; HBG="$B/raw/ph_at_launch/live/state/fleet_capture.hb"
mkdir -p $L $S $W/secrets $W/phlaunch/live_ts; : > $W/gcp-auth.sh; chmod 700 $W/secrets
log() { echo "$(date -u +%FT%TZ) $*"; }
gsutil -q cp "$T/*.py" $L/ || { log "code fetch failed"; exit 1; }
until v=$(gcloud secrets versions access latest --secret="${PH_TOKEN_SECRET:-PH_API_TOKEN}" 2>/dev/null) && [ -n "$v" ]; do
  log "waiting for secret ${PH_TOKEN_SECRET:-PH_API_TOKEN}"; echo "$(date -u +%FT%TZ) waiting_token" | gsutil -q cp - "$HBG" 2>/dev/null; sleep 300
done
umask 077; printf 'PH_TOKEN=%s\n' "$v" > $W/secrets/ph_dev_token.env; unset v; umask 022
log "token ready, capture loop starting"
last=""
while true; do
  read -r F HH MM < <(TZ=America/Los_Angeles date '+%F %H %M'); M=$((10#$MM)); Q=${F}_${HH}$((M / 15))
  if [ "$Q" != "$last" ]; then
    last=$Q; Y=$(TZ=America/Los_Angeles date -d "$F -1 day" +%F)
    SM=$(printf %02d $(( M / 15 * 15 ))); [ "$HH$SM" = "0000" ] && SM=01; PS=${F//-/}T${HH}${SM}
    for d in $F $Y; do
      if gsutil -q stat "$B/raw/ph_at_launch/$d/snapshots/${PS}PT_api.jsonl" 2>/dev/null; then log "skip $d $PS: already written"; continue; fi
      (cd $L && PLANNED_SLOT=$PS timeout 120 python3 api_snap.py $d) && log "wrote $d $PS" || log "api_snap $d failed (slot $PS)"
    done
    echo "$(date -u +%FT%TZ) slot=$PS" | gsutil -q cp - "$HBG" 2>/dev/null
  fi
  sleep 20
done
