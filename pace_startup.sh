#!/bin/bash
# Pace feeder boot: install Camoufox once, refresh reuse.tgz, run strategy-aware phsuper.
exec >> /var/log/phreuse_start.log 2>&1
mkdir -p /opt/ph /opt/ph/overlays /opt/ph/out /opt/ph/reuse/out
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
mark() {
  # Structured setup timeline (UTC). Consumed by ph_tab_strategy_experiment.sh setup.
  mkdir -p /opt/ph/reuse
  printf '{"event":"%s","utc":"%s"}\n' "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /opt/ph/reuse/setup_timing.jsonl
}
mark startup_begin

curl -sf -H Metadata-Flavor:Google "$MD/pace-boot-env" >/opt/ph/pace.env 2>/dev/null || true
if [[ -f /opt/ph/pace.env ]]; then
  set -a
  # shellcheck source=/dev/null
  source /opt/ph/pace.env
  set +a
fi

curl -sf -H Metadata-Flavor:Google "$MD/ph-strategy-env" >/opt/ph/strategy.env 2>/dev/null || true
if [[ -f /opt/ph/strategy.env ]]; then
  set -a
  # shellcheck source=/dev/null
  source /opt/ph/strategy.env
  set +a
fi

B="${PACE_GCS_VM_ROOT:-gs://${MVP_GCS_BUCKET:?pace-boot-env missing MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"

# Fetch strategy overlays (portscreen pool + supervisor wrapper + args mapper).
gcloud storage cp -q "$B/_code/overlays/supervisor_strat.sh" /opt/ph/overlays/ 2>/dev/null || true
gcloud storage cp -q "$B/_code/overlays/portscreen.py" /opt/ph/overlays/ 2>/dev/null || true
gcloud storage cp -q "$B/_code/overlays/strategy_args.py" /opt/ph/overlays/ 2>/dev/null || true
gcloud storage cp -q "$B/_code/overlays/ensure_geoip.sh" /opt/ph/overlays/ 2>/dev/null || true
gcloud storage cp -q "$B/_code/overlays/proxy_geo_sync.sh" /opt/ph/overlays/ 2>/dev/null || true
gcloud storage cp -q "$B/_code/overlays/setup_probe.py" /opt/ph/overlays/ 2>/dev/null || true
chmod +x /opt/ph/overlays/supervisor_strat.sh /opt/ph/overlays/ensure_geoip.sh /opt/ph/overlays/proxy_geo_sync.sh 2>/dev/null || true

if [ ! -x /opt/venv/bin/python ]; then
  mark cold_install_begin
  apt-get update -q && apt-get install -yq python3-venv xvfb libgtk-3-0 libx11-xcb1 libasound2 libdbus-glib-1-2 >/dev/null
  python3 -m venv /opt/venv && /opt/venv/bin/pip -q install "camoufox[geoip]==0.5.9" playwright==1.62.0 && /opt/venv/bin/python -m camoufox fetch >/dev/null
  touch /opt/ph/installed
  mark cold_install_end
else
  mark warm_image_ready
fi

# Kill the launch→identity GeoIP tax: restore cache if needed, then touch mmdb mtimes.
mark geoip_ensure_begin
if [[ -x /opt/ph/overlays/ensure_geoip.sh ]]; then
  PACE_GCS_VM_ROOT="$B" bash /opt/ph/overlays/ensure_geoip.sh >> /var/log/phreuse_start.log 2>&1 || true
fi
mark geoip_ensure_end

if [[ -x /opt/ph/overlays/proxy_geo_sync.sh ]]; then
  PACE_GCS_VM_ROOT="$B" bash /opt/ph/overlays/proxy_geo_sync.sh >> /var/log/phreuse_start.log 2>&1 || true
fi

mkdir -p /opt/ph/reuse
cd /opt/ph/reuse
mark reuse_fetch_begin
(gcloud storage cp -q "$B/_code/reuse.tgz" . 2>/dev/null || gsutil -q cp "$B/_code/reuse.tgz" .) && tar xzf reuse.tgz
mark reuse_fetch_end
[[ -f /opt/ph/overlays/portscreen.py ]] && cp -f /opt/ph/overlays/portscreen.py /opt/ph/reuse/portscreen.py
[[ -f /opt/ph/overlays/strategy_args.py ]] && cp -f /opt/ph/overlays/strategy_args.py /opt/ph/reuse/strategy_args.py
[[ -f /opt/ph/overlays/ensure_geoip.sh ]] && cp -f /opt/ph/overlays/ensure_geoip.sh /opt/ph/reuse/ensure_geoip.sh
[[ -f /opt/ph/overlays/setup_probe.py ]] && cp -f /opt/ph/overlays/setup_probe.py /opt/ph/reuse/setup_probe.py
gcloud storage cp -q "$B/_code/overlays/patch_week_bytes.py" \
  "$B/_code/overlays/patch_stop_first_block.py" \
  "$B/_code/overlays/patch_dynamic_paged.py" \
  "$B/_code/overlays/patch_soft_block_rotate.py" \
  "$B/_code/overlays/patch_soft_open_rotate.py" \
  "$B/_code/overlays/patch_same_port_retry.py" \
  "$B/_code/overlays/patch_lazy_tabs.py" \
  "$B/_code/overlays/patch_require_full_save.py" \
  "$B/_code/overlays/patch_pdeep_partition.py" \
  "$B/_code/overlays/patch_cf_fast_fail.py" /opt/ph/overlays/ 2>/dev/null || true
if [[ -x /opt/venv/bin/python && -f /opt/ph/reuse/ph_batch.py ]]; then
  for _patch in patch_week_bytes.py patch_stop_first_block.py patch_dynamic_paged.py patch_soft_block_rotate.py patch_soft_open_rotate.py patch_same_port_retry.py patch_lazy_tabs.py patch_require_full_save.py patch_pdeep_partition.py patch_cf_fast_fail.py; do
  if [[ -f /opt/ph/overlays/$_patch ]]; then
    mark "patch_${_patch%.py}_begin"
    /opt/venv/bin/python "/opt/ph/overlays/$_patch" >>/var/log/phreuse_start.log 2>&1 || true
    mark "patch_${_patch%.py}_end"
  fi
  done
fi

# Golden-image hygiene: quarantine baked outputs/profiles so strat metrics & sticky ports stay clean.
if [[ -f /opt/ph/strategy.env ]] && [[ ! -f /opt/ph/reuse/.strat_cleaned ]]; then
  mkdir -p /opt/ph/golden_quarantine
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  if [[ -d /opt/ph/reuse/out ]]; then
    mv /opt/ph/reuse/out "/opt/ph/golden_quarantine/out.$ts" 2>/dev/null || rm -rf /opt/ph/reuse/out
  fi
  mkdir -p /opt/ph/reuse/out
  rm -f /opt/ph/reuse/last_token
  mkdir -p /opt/ph/golden_quarantine/logs
  shopt -s nullglob
  for f in /opt/ph/reuse/run_*.log; do mv "$f" /opt/ph/golden_quarantine/logs/ 2>/dev/null || true; done
  shopt -u nullglob
  rm -rf /opt/ph/profiles
  mkdir -p /opt/ph/profiles
  touch /opt/ph/reuse/.strat_cleaned
  mark golden_hygiene_done
fi

systemctl stop phsuper 2>/dev/null || true
SUP=/opt/ph/overlays/supervisor_strat.sh
[[ -x "$SUP" ]] || SUP=/opt/ph/reuse/supervisor.sh
ENV_ARGS=()
[[ -f /opt/ph/pace.env ]] && ENV_ARGS+=(-p "EnvironmentFile=/opt/ph/pace.env")
[[ -f /opt/ph/strategy.env ]] && ENV_ARGS+=(-p "EnvironmentFile=/opt/ph/strategy.env")
mark supervisor_start
systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse \
  "${ENV_ARGS[@]}" \
  /bin/bash -c "bash $SUP >> /opt/ph/reuse/supervisor.log 2>&1"
