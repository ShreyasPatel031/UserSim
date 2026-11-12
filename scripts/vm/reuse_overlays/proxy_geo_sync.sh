#!/bin/bash
# When GCE proxy-url metadata changes, wipe Camoufox profiles so geoip matches egress IP.
# (ph_batch stable_options keys fingerprint per port; stale launch.json breaks Finland/Spain swaps.)
set -euo pipefail
MARK=/opt/ph/reuse/.bound_proxy_key
MD="${MD:-http://metadata.google.internal/computeMetadata/v1/instance/attributes}"
proxy_key() {
  python3 - <<'PY'
import hashlib, os, urllib.parse as up
u = os.environ.get("PROXY_URL") or ""
try:
    u = __import__("urllib.request").request.urlopen(
        __import__("urllib.request").Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/attributes/proxy-url",
            headers={"Metadata-Flavor": "Google"},
        ),
        timeout=5,
    ).read().decode()
except Exception:
    pass
p = up.urlparse(u.strip())
host = p.hostname or ""
port = p.port or ""
user = p.username or ""
key = f"{host}:{port}:{user}"
print(hashlib.sha256(key.encode()).hexdigest()[:16], host or "?", sep="\t")
PY
}

read -r new_key new_host <<<"$(proxy_key | tr '\t' ' ')"
old_key=""
old_host=""
if [[ -f "$MARK" ]]; then
  read -r old_key old_host _ <"$MARK" || true
fi

if [[ "$new_key" == "$old_key" && -n "$old_key" ]]; then
  exit 0
fi

echo "proxy_geo_sync: proxy changed ${old_host:-?} -> ${new_host} (wiping profiles)"
rm -rf /opt/ph/profiles/* 2>/dev/null || true
mkdir -p /opt/ph/profiles
echo "$new_key $new_host $(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$MARK"
if [[ -x /opt/ph/overlays/ensure_geoip.sh ]]; then
  PACE_GCS_VM_ROOT="${PACE_GCS_VM_ROOT:-}" bash /opt/ph/overlays/ensure_geoip.sh >>/opt/ph/reuse/supervisor.log 2>&1 || true
fi
