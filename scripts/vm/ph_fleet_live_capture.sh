#!/bin/bash
# Fleet primary for 15-min PH live capture on FLEET_LIVE_SLOTS (default 39). Box is standby (dedupe via cp -n).
# Token: Secret Manager PH_API_TOKEN (exact ph_dev_token.env bytes). live_ts_writer.py loop builds posts_ts/comments_ts/board_ts.
set -u
B="${PH_GCS_ROOT:-gs://${MVP_GCS_BUCKET:?}/usersim_sim}"
T="$B/raw/ph_at_launch/live/tools"
W=/workspace; L=$W/phlaunch/live; HBG="$B/raw/ph_at_launch/live/state/fleet_capture.hb"
STANDBY_SEC="${FLEET_CAPTURE_STANDBY_SEC:-0}"
mkdir -p $L $W/secrets $W/phlaunch/live_ts $W/phlaunch/live
chmod 777 "$W/phlaunch/live_ts" "$W/phlaunch/live" 2>/dev/null || true
: > $W/gcp-auth.sh; chmod 700 $W/secrets
log() { echo "$(date -u +%FT%TZ) $*"; }
gsutil -q cp "$T/api_loop/*.py" $L/ || { log "api_loop code fetch failed"; exit 1; }
gsutil -q cp "$T/live_ts_writer.py" $W/phlaunch/ || { log "live_ts_writer fetch failed"; exit 1; }
fetch_token() {
  gcloud secrets versions access latest --secret="${PH_TOKEN_SECRET:-PH_API_TOKEN}" \
    ${GCP_PROJECT:+--project="$GCP_PROJECT"} 2>/dev/null
}
until raw=$(fetch_token) && [ -n "$raw" ]; do
  log "waiting for secret ${PH_TOKEN_SECRET:-PH_API_TOKEN}"
  echo "$(date -u +%FT%TZ) waiting_token" | gsutil -q cp - "$HBG" 2>/dev/null
  sleep 60
done
umask 077; printf '%s' "$raw" > "$W/secrets/ph_dev_token.env"; unset raw; umask 022
log "token ready; primary capture standby_delay=${STANDBY_SEC}s"
(setsid bash -c 'while true; do python3 /workspace/phlaunch/live_ts_writer.py loop >>/var/log/phlive_ts.log 2>&1; sleep 60; done') &
last_ps=""
while true; do
  read -r F HH MM < <(TZ=America/Los_Angeles date '+%F %H %M')
  M=$((10#$MM)); SM=$((M / 15 * 15)); slot_min=$((M - SM))
  [ "$HH$SM" = "0000" ] && SM=01
  PS=${F//-/}T$(printf %02d "$HH")$(printf %02d "$SM")
  Y=$(TZ=America/Los_Angeles date -d "$F -1 day" +%F)
  if [ "$STANDBY_SEC" -gt 0 ]; then
    need_min=$((STANDBY_SEC / 60))
    [ "$slot_min" -lt "$need_min" ] && { sleep 15; continue; }
  fi
  if [ "$PS" = "$last_ps" ]; then
    sleep 20; continue
  fi
  wrote=0
  for d in $F $Y; do
    dst="$B/raw/ph_at_launch/$d/snapshots/${PS}PT_api.jsonl"
    if gsutil -q stat "$dst" 2>/dev/null; then
      log "dedupe skip $d $PS (already present)"
    else
      if (cd "$L" && PLANNED_SLOT="$PS" timeout 120 python3 api_snap.py "$d"); then
        log "wrote $d $PS"
        wrote=1
      else
        log "api_snap failed $d $PS"
      fi
    fi
  done
  last_ps=$PS
  echo "$(date -u +%FT%TZ) slot=$PS wrote=$wrote primary" | gsutil -q cp - "$HBG" 2>/dev/null
  sleep 20
done