#!/bin/bash
# Strategy-experiment supervisor: stock loop + overlays + PH_* -> ph_batch args.
# Launched by pace_startup instead of stock supervisor.sh so reuse.tgz self-update
# cannot clobber strategy wiring. Never prints secrets.
set -u
if [[ -f /opt/ph/pace.env ]]; then
  set -a
  # shellcheck source=/dev/null
  source /opt/ph/pace.env
  set +a
fi
B="${PACE_GCS_VM_ROOT:?PACE_GCS_VM_ROOT unset}"
VM=$(hostname)
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
OVERLAYS="${PH_OVERLAYS_DIR:-/opt/ph/overlays}"
export PROXY_PORT=$(curl -s -H Metadata-Flavor:Google "$MD/proxy-port")
# A port moved to after a block survives supervisor restarts (metadata still holds the walled home port).
_po=$(cat /opt/ph/reuse/port_override 2>/dev/null | tr -cd 0-9)
[[ -n "$_po" ]] && export PROXY_PORT="$_po"
export PROXY_URL=$(curl -s -H Metadata-Flavor:Google "$MD/proxy-url")
export PROXY_URL=$(python3 -c 'import os,urllib.parse as up;u=os.environ["PROXY_URL"];p=up.urlparse(u);print(u if ("dataimpulse" not in (p.hostname or "") or "__cr." in (p.username or "")) else u.replace("//"+p.username+":","//"+p.username+"__cr.us:",1))')

load_strategy() {
  curl -sf -H Metadata-Flavor:Google "$MD/ph-strategy-env" >/opt/ph/strategy.env.new 2>/dev/null || true
  if [[ -s /opt/ph/strategy.env.new ]]; then
    mv /opt/ph/strategy.env.new /opt/ph/strategy.env
  fi
  if [[ -f /opt/ph/strategy.env ]]; then
    set -a
    # shellcheck source=/dev/null
    source /opt/ph/strategy.env
    set +a
  fi
  # Population (full7): pending saves go to a separate folder; Population merges only people who pass.
  if [[ -n "${PH_SAVE_B_SUFFIX:-}" ]]; then
    export PH_SAVE_B="${B%/ph_population/people_live/vm}/${PH_SAVE_B_SUFFIX}"
  fi
}

apply_overlays() {
  if [[ -f "$OVERLAYS/portscreen.py" ]]; then
    cp -f "$OVERLAYS/portscreen.py" /opt/ph/reuse/portscreen.py
  fi
  if [[ -f "$OVERLAYS/strategy_args.py" ]]; then
    cp -f "$OVERLAYS/strategy_args.py" /opt/ph/reuse/strategy_args.py
  fi
  if [[ -f "$OVERLAYS/setup_probe.py" ]]; then
    cp -f "$OVERLAYS/setup_probe.py" /opt/ph/reuse/setup_probe.py
  fi
  # Refresh patches from GCS each loop (reuse.tgz unpack can clobber).
  gcloud storage cp -q "$B/_code/overlays/patch_week_bytes.py" \
    "$B/_code/overlays/patch_week_start.py" \
    "$B/_code/overlays/patch_stop_first_block.py" \
    "$B/_code/overlays/patch_dynamic_paged.py" \
    "$B/_code/overlays/patch_soft_block_rotate.py" \
    "$B/_code/overlays/patch_soft_open_rotate.py" \
    "$B/_code/overlays/patch_same_port_retry.py" \
    "$B/_code/overlays/patch_lazy_tabs.py" \
    "$B/_code/overlays/patch_require_full_save.py" \
    "$B/_code/overlays/patch_pdeep_partition.py" \
    "$B/_code/overlays/patch_pdeep_rr_only.py" \
    "$B/_code/overlays/patch_pdeep_coverage_queue.py" \
    "$B/_code/overlays/patch_same_ip_only.py" \
    "$B/_code/overlays/patch_cf_fast_fail.py" "$OVERLAYS/" 2>/dev/null || true
  for _patch in patch_week_bytes.py patch_week_start.py patch_stop_first_block.py patch_dynamic_paged.py patch_soft_block_rotate.py patch_soft_open_rotate.py patch_same_port_retry.py patch_same_ip_only.py patch_lazy_tabs.py patch_require_full_save.py patch_pdeep_partition.py patch_pdeep_rr_only.py patch_pdeep_coverage_queue.py patch_cf_fast_fail.py; do
    if [[ -f "$OVERLAYS/$_patch" && -x $PY ]]; then
      $PY "$OVERLAYS/$_patch" >>supervisor.log 2>&1 || true
    fi
  done
}

mkdir -p /opt/ph/reuse/out && cd /opt/ph/reuse
PY=/opt/venv/bin/python
last=$(cat last_token 2>/dev/null || true)
crashes=0
HB="${B%/vm}/heartbeat"
gsutil -q rm "$B/heartbeat.$VM.json" 2>/dev/null || true
hb(){ echo "{\"vm\":\"$VM\",\"utc\":\"$(date -u +%FT%TZ)\",\"last_token\":\"$last\",\"running\":\"$1\",\"strat\":\"${PH_STRATEGY:-}\"}" > hb.json; gsutil -q cp hb.json "$HB/heartbeat.$VM.json" || true; }

mark() {
  printf '{"event":"%s","utc":"%s","strat":"%s","detail":"%s"}\n' \
    "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${PH_STRATEGY:-}" "${2:-}" >> /opt/ph/reuse/setup_timing.jsonl
}

apply_proxy_port() {
  if [[ "${PH_PROXY_FIXED_PORT:-0}" == "1" ]]; then
    export PROXY_PORT=$(python3 -c 'import os,urllib.parse as up;u=os.environ["PROXY_URL"];print(up.urlparse(u).port or os.environ.get("PROXY_PORT",""))')
  fi
}
load_strategy
apply_proxy_port
if [[ -x /opt/ph/overlays/proxy_geo_sync.sh ]]; then
  PACE_GCS_VM_ROOT="$B" bash /opt/ph/overlays/proxy_geo_sync.sh >>supervisor.log 2>&1 || true
fi
echo "supervisor_strat start $(date -u +%FT%TZ) strategy=${PH_STRATEGY:-none} home_port=${PROXY_PORT}" >> /opt/ph/reuse/supervisor.log
mark supervisor_ready "home_port=${PROXY_PORT}"

_cf_cooldown_active() {
  [[ -f /opt/ph/reuse/cf_cooldown_until ]] || return 1
  local until now
  until=$(cat /opt/ph/reuse/cf_cooldown_until 2>/dev/null | tr -cd 0-9)
  now=$(date +%s)
  [[ -n "$until" && "$now" -lt "$until" ]]
}

while true; do
  gsutil -q cp "$B/_code/reuse.tgz" . && tar xzf reuse.tgz
  apply_overlays
  load_strategy
  apply_proxy_port
  export PKG_MD5=$(python3 -c 'import hashlib,base64;print(base64.b64encode(hashlib.md5(open("reuse.tgz","rb").read()).digest()).decode())' 2>/dev/null)
  tok=$(gsutil cat "$B/GO.$VM" 2>/dev/null | head -1 | tr -cd 'A-Za-z0-9:_.-' || true)
  batch_up=0
  pgrep -f '[p]h_batch.py|[p]deep.py' >/dev/null 2>&1 && batch_up=1
  do_launch=0
  launch_reason=""
  if _cf_cooldown_active; then
    rem=$(( $(cat /opt/ph/reuse/cf_cooldown_until | tr -cd 0-9) - $(date +%s) ))
    echo "cf_cooldown ${rem}s left; no relaunch" >> supervisor.log
    hb "${tok:-}"
  elif [[ -n "$tok" && "$tok" != "$last" ]]; then
    do_launch=1
    launch_reason="new_go"
  elif [[ -n "$tok" && "$tok" == "$last" && $batch_up -eq 0 ]]; then
    now_s=$(date +%s)
    retry_at=0
    [[ -f /opt/ph/reuse/same_tok_retry_at ]] && retry_at=$(cat /opt/ph/reuse/same_tok_retry_at 2>/dev/null | tr -cd 0-9)
    if [[ -n "$retry_at" && "$now_s" -lt "$retry_at" ]]; then
      :
    else
      do_launch=1
      launch_reason="same_tok_retry"
    fi
  fi
  if [[ $do_launch -eq 1 ]]; then
    if [[ "${PH_FLEET_BLOCK_PAUSE:-0}" == "1" ]]; then
      echo "fleet_block_pause; ack GO $tok without launch ($(date -u +%FT%TZ))" >> supervisor.log
      last=$tok
      echo "$tok" > last_token
    else
    mode=${tok%%:*}
    L=run_$(date -u +%Y%m%dT%H%MZ).log
    if [[ "$mode" = "legacy" ]]; then mode=run; echo "legacy->$tok as run" >> supervisor.log; fi
    extra=$($PY strategy_args.py 2>>supervisor.log || true)
    echo "launch $tok reason=$launch_reason mode=$mode extra=[$extra] $(date -u +%FT%TZ)" >> supervisor.log
    mark batch_launch "token=$tok extra=$extra"
    if [[ -x /opt/ph/overlays/proxy_geo_sync.sh ]]; then
      PACE_GCS_VM_ROOT="$B" bash /opt/ph/overlays/proxy_geo_sync.sh >>supervisor.log 2>&1 || true
    fi
    # Refresh GeoIP mtime every launch so camoufox never re-downloads mid-session.
    if [[ -x /opt/ph/overlays/ensure_geoip.sh ]]; then
      mark geoip_ensure_begin
      PACE_GCS_VM_ROOT="$B" bash /opt/ph/overlays/ensure_geoip.sh >> supervisor.log 2>&1 || true
      mark geoip_ensure_end
    fi
    # shellcheck disable=SC2086
    PYTHONUNBUFFERED=1 $PY -u ph_batch.py --mode "$mode" --token "$tok" $extra >"$L" 2>&1 &
    pid=$!
    hb "$tok"
    # Watch the run log for identity-ready + first pull (setup ends when pulling starts).
    (
      saw_fp=0; saw_pull=0
      for _ in $(seq 1 720); do
        [[ -f "$L" ]] || { sleep 2; continue; }
        if [[ $saw_fp -eq 0 ]] && grep -qE 'FINGERPRINT_(NEW|REUSED)' "$L" 2>/dev/null; then
          mark identity_ready "$(grep -E 'FINGERPRINT_(NEW|REUSED)' "$L" | head -1 | tr '"' "'")"
          saw_fp=1
        fi
        if [[ $saw_pull -eq 0 ]] && grep -qE ' paged | paged_v2 ' "$L" 2>/dev/null; then
          mark first_pull "$(grep -E ' paged | paged_v2 ' "$L" | head -1 | tr '"' "'")"
          saw_pull=1
        fi
        [[ $saw_fp -eq 1 && $saw_pull -eq 1 ]] && break
        kill -0 "$pid" 2>/dev/null || break
        sleep 2
      done
    ) &
    _up=$SECONDS
    while kill -0 "$pid" 2>/dev/null; do
      sleep 5
      if (( SECONDS - _up >= 120 )); then
        _up=$SECONDS
        gsutil -q cp "$L" "$B/logs/$VM.reuse.$L" || true
        hb "$tok"
      fi
    done
    wait "$pid"
    rc=$?
    gsutil -q cp "$L" "$B/logs/$VM.reuse.$L" || true
    [[ $rc -eq 7 ]] && echo "halted by autorecover; waiting for NEW GO token" >> supervisor.log
    echo "{\"vm\":\"$VM\",\"event\":\"supervisor_run_end\",\"token\":\"$tok\",\"pkg_md5\":\"$PKG_MD5\",\"rc\":$rc,\"utc\":\"$(date -u +%FT%TZ)\",\"strat\":\"${PH_STRATEGY:-}\",\"extra\":\"$extra\"}" >> "status_$VM.jsonl"
    gsutil -q cp "status_$VM.jsonl" "$B/status/$VM.supervisor.jsonl" || true
    kicked=0; [[ -f /opt/ph/reuse/KICK ]] && { kicked=1; rm -f /opt/ph/reuse/KICK; }
    if [[ ( $rc -eq 3 || $kicked -eq 1 ) && "${PH_BLOCK_NEW_PORT:-0}" == "1" ]]; then
      # Blocked / Cloudflare not cleared (or kicked by the fleet wall check): new free port, relaunch the same token.
      oldp="$PROXY_PORT"
      newp=$(PH_PORTSCREEN_HOME_ONLY=0 PH_PORTSCREEN_MAX_TRY="${PH_PORTSCREEN_MAX_TRY_ON_BLOCK:-24}" \
        $PY -c 'import os, portscreen as p; p.FAILED.add(int(os.environ.get("PROXY_PORT") or 0)); print(p.prescreen(os.uname()[1], lambda **k: None) or "")' \
        2>>supervisor.log | tail -1)
      [[ -n "$newp" ]] && { export PROXY_PORT="$newp"; echo "$newp" > /opt/ph/reuse/port_override; }
      mark block_new_port "from=$oldp to=${newp:-none}"
      echo "block rc=3: port $oldp -> ${newp:-unchanged}; rest ${PH_BLOCK_REST_SEC:-60}s then relaunch $tok" >> supervisor.log
      sleep "${PH_BLOCK_REST_SEC:-60}"
      continue
    fi
    if [[ $rc -eq 3 || $kicked -eq 1 ]]; then
      base=${PH_CF_FLEET_REST_SEC:-600}
      n=0; [[ -f /opt/ph/reuse/cf_backoff_n ]] && n=$(($(cat /opt/ph/reuse/cf_backoff_n | tr -cd 0-9)))
      n=$((n + 1)); echo "$n" > /opt/ph/reuse/cf_backoff_n
      mult=1
      (( n > 1 )) && mult=2
      (( n > 2 )) && mult=4
      (( n > 3 )) && mult=8
      wait=$(( base * mult ))
      (( wait > 3600 )) && wait=3600
      echo $(( $(date +%s) + wait )) > /opt/ph/reuse/cf_cooldown_until
      echo $(( $(date +%s) + wait )) > /opt/ph/reuse/same_tok_retry_at
      echo "block rc=$rc same-ip; cooldown ${wait}s (n=$n) — no relaunch storm" >> supervisor.log
      last=$tok; echo "$tok" > last_token
    elif [[ $rc -eq 0 ]]; then
      rm -f /opt/ph/reuse/cf_cooldown_until /opt/ph/reuse/cf_backoff_n /opt/ph/reuse/same_tok_retry_at
    else
      base=${PH_CF_FLEET_REST_SEC:-600}
      n=0; [[ -f /opt/ph/reuse/cf_backoff_n ]] && n=$(($(cat /opt/ph/reuse/cf_backoff_n 2>/dev/null | tr -cd 0-9)))
      mult=1
      (( n > 1 )) && mult=2
      (( n > 2 )) && mult=4
      (( n > 3 )) && mult=8
      wait=$(( base * mult ))
      (( wait > 3600 )) && wait=3600
      echo $(( $(date +%s) + wait )) > /opt/ph/reuse/same_tok_retry_at
    fi
    if [[ $rc -eq 1 && $crashes -lt 3 ]]; then
      crashes=$((crashes + 1))
      sleep 300
    elif [[ $rc -ne 3 && $kicked -eq 0 ]]; then
      last=$tok
      echo "$tok" > last_token
      crashes=0
    fi
    fi
  fi
  hb ""
  if [[ -n "${tok:-}" && $batch_up -eq 0 && "${tok:-}" == "$last" ]]; then
    sleep 5
  else
    sleep 60
  fi
done
