#!/bin/bash
# Keep Camoufox from re-downloading GeoIP on every session (huge launch→identity tax).
# needs_update() rechecks when mmdb mtime is older than RECHECK_DAYS (1). Touching
# the file after ensure makes needs_update False even if the DB build is old.
set -euo pipefail
if [[ "${EUID:-$(id -u)}" -ne 0 ]] && command -v sudo >/dev/null; then
  exec sudo -n env PACE_GCS_VM_ROOT="${PACE_GCS_VM_ROOT:-}" FORCE_GEOIP_REFRESH="${FORCE_GEOIP_REFRESH:-}" CAMOUFOX_GEOIP_CACHE="${CAMOUFOX_GEOIP_CACHE:-}" "$0" "$@"
fi
CACHE="${CAMOUFOX_GEOIP_CACHE:-/root/.cache/camoufox}"
MMDB_DIR="$CACHE/geoip/mmdb"
B="${PACE_GCS_VM_ROOT:-}"
mkdir -p "$MMDB_DIR"

has_mmdb() { compgen -G "$MMDB_DIR/*.mmdb" >/dev/null; }

if ! has_mmdb && [[ -n "$B" ]]; then
  echo "ensure_geoip: restoring from GCS"
  gcloud storage cp -q "$B/_code/camoufox-geoip.tgz" /tmp/camoufox-geoip.tgz 2>/dev/null || true
  if [[ -f /tmp/camoufox-geoip.tgz ]]; then
    mkdir -p "$CACHE"
    tar xzf /tmp/camoufox-geoip.tgz -C "$CACHE"
  fi
fi

if [[ -x /opt/venv/bin/python ]] && { ! has_mmdb || [[ "${FORCE_GEOIP_REFRESH:-0}" == 1 ]]; }; then
  echo "ensure_geoip: downloading via camoufox (one-time)"
  /opt/venv/bin/python - <<'PY' || true
from camoufox.geolocation import download_mmdb
download_mmdb()
PY
fi

if has_mmdb; then
  # Critical: refresh mtime so needs_update() short-circuits (RECHECK_DAYS=1).
  find "$MMDB_DIR" -name '*.mmdb' -exec touch {} +
  echo "ensure_geoip: ready ($(ls "$MMDB_DIR"/*.mmdb 2>/dev/null | wc -l) mmdb)"
  exit 0
fi
echo "ensure_geoip: FAILED no mmdb" >&2
exit 1
