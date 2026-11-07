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

load_strategy
echo "supervisor_strat start $(date -u +%FT%TZ) strategy=${PH_STRATEGY:-none} home_port=${PROXY_PORT}" >> /opt/ph/reuse/supervisor.log
mark supervisor_ready "home_port=${PROXY_PORT}"

while true; do
  gsutil -q cp "$B/_code/reuse.tgz" . && tar xzf reuse.tgz
  apply_overlays
  load_strategy
  export PKG_MD5=$(python3 -c 'import hashlib,base64;print(base64.b64encode(hashlib.md5(open("reuse.tgz","rb").read()).digest()).decode())' 2>/dev/null)
  tok=$(gsutil cat "$B/GO.$VM" 2>/dev/null | head -1 | tr -cd 'A-Za-z0-9:_.-' || true)
  if [[ -n "$tok" && "$tok" != "$last" ]]; then
    mode=${tok%%:*}
    L=run_$(date -u +%Y%m%dT%H%MZ).log
    if [[ "$mode" = "legacy" ]]; then mode=run; echo "legacy->$tok as run" >> supervisor.log; fi
    extra=$($PY strategy_args.py 2>>supervisor.log || true)
    echo "launch $tok mode=$mode extra=[$extra] $(date -u +%FT%TZ)" >> supervisor.log
    mark batch_launch "token=$tok extra=$extra"
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
    while kill -0 "$pid" 2>/dev/null; do
      sleep 120
      gsutil -q cp "$L" "$B/logs/$VM.reuse.$L" || true
      hb "$tok"
    done
    wait "$pid"
    rc=$?
    gsutil -q cp "$L" "$B/logs/$VM.reuse.$L" || true
    [[ $rc -eq 7 ]] && echo "halted by autorecover; waiting for NEW GO token" >> supervisor.log
    echo "{\"vm\":\"$VM\",\"event\":\"supervisor_run_end\",\"token\":\"$tok\",\"pkg_md5\":\"$PKG_MD5\",\"rc\":$rc,\"utc\":\"$(date -u +%FT%TZ)\",\"strat\":\"${PH_STRATEGY:-}\",\"extra\":\"$extra\"}" >> "status_$VM.jsonl"
    gsutil -q cp "status_$VM.jsonl" "$B/status/$VM.supervisor.jsonl" || true
    if [[ $rc -eq 1 && $crashes -lt 3 ]]; then
      crashes=$((crashes + 1))
      sleep 300
    else
      last=$tok
      echo "$tok" > last_token
      crashes=0
    fi
  fi
  hb ""
  sleep 60
done
