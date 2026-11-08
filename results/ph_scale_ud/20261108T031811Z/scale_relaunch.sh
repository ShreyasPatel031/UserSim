#!/bin/bash
set +e
STRAT_FILE="${1:?scale_up.env|scale_down.env}"
B=$(grep PACE_GCS_VM_ROOT /opt/ph/pace.env | cut -d= -f2-)
gcloud storage cp -q "$B/_code/overlays/supervisor_strat.sh" "$B/_code/overlays/portscreen.py" \
  "$B/_code/overlays/strategy_args.py" "$B/_code/overlays/ensure_geoip.sh" \
  "$B/_code/overlays/patch_week_bytes.py" "$B/_code/overlays/patch_stop_first_block.py" /opt/ph/overlays/
gcloud storage cp -q "$B/_code/overlays/${STRAT_FILE}" /opt/ph/strategy.env
chmod +x /opt/ph/overlays/ensure_geoip.sh /opt/ph/overlays/supervisor_strat.sh
PACE_GCS_VM_ROOT="$B" bash /opt/ph/overlays/ensure_geoip.sh
cp -f /opt/ph/overlays/portscreen.py /opt/ph/reuse/portscreen.py
cp -f /opt/ph/overlays/strategy_args.py /opt/ph/reuse/strategy_args.py
# Re-apply patches after every reuse.tgz unpack
if ! grep -q patch_week_bytes /opt/ph/overlays/supervisor_strat.sh; then
  awk '
    /apply_overlays/ && !done {
      print
      print "  gcloud storage cp -q \"$B/_code/overlays/patch_week_bytes.py\" \"$B/_code/overlays/patch_stop_first_block.py\" /opt/ph/overlays/ 2>/dev/null || true"
      print "  /opt/venv/bin/python /opt/ph/overlays/patch_week_bytes.py >> supervisor.log 2>&1 || true"
      print "  /opt/venv/bin/python /opt/ph/overlays/patch_stop_first_block.py >> supervisor.log 2>&1 || true"
      done=1; next
    }
    { print }
  ' /opt/ph/overlays/supervisor_strat.sh > /tmp/sup.sh && mv /tmp/sup.sh /opt/ph/overlays/supervisor_strat.sh
fi
sed -i -E '/^PH_(STRATEGY|TABS|BROWSER_TABS|MAX_INFLIGHT|RAMP|REQ_PER_MIN|PERSON_INTERVAL|START_|AIMD_|BURST_|COAST_|LAZY_|CIRCUIT_|INTER_REQ|SKIP_|SERIALIZE_|STOP_ON)/d' /opt/ph/pace.env
grep -q PH_PORTSCREEN_HOME_ONLY= /opt/ph/pace.env || echo PH_PORTSCREEN_HOME_ONLY=1 >> /opt/ph/pace.env
systemctl stop phsuper 2>/dev/null || true
pkill -f ph_batch.py 2>/dev/null || true
sleep 1
rm -f /opt/ph/reuse/last_token
rm -rf /opt/ph/profiles
mkdir -p /opt/ph/profiles /opt/ph/golden_quarantine
mv /opt/ph/reuse/out "/opt/ph/golden_quarantine/out.scaleud.$(date -u +%Y%m%dT%H%M%SZ)" 2>/dev/null || true
mkdir -p /opt/ph/reuse/out
: > /opt/ph/reuse/setup_timing.jsonl
/opt/venv/bin/python /opt/ph/overlays/patch_week_bytes.py || true
/opt/venv/bin/python /opt/ph/overlays/patch_stop_first_block.py || true
set -a; source /opt/ph/pace.env; source /opt/ph/strategy.env; set +a
echo -n "args="; /opt/venv/bin/python /opt/ph/reuse/strategy_args.py; echo
echo "STOP_ON_FIRST_BLOCK=${PH_STOP_ON_FIRST_BLOCK:-}"
grep -n "STOP_ON_FIRST_BLOCK_PATCH\|WEEK_BYTES_CACHE" /opt/ph/reuse/ph_batch.py | head -6
systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse \
  -p EnvironmentFile=/opt/ph/pace.env -p EnvironmentFile=/opt/ph/strategy.env \
  /bin/bash -c 'bash /opt/ph/overlays/supervisor_strat.sh >> /opt/ph/reuse/supervisor.log 2>&1'
sleep 1
systemctl is-active phsuper || true
echo DONE
