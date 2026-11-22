#!/usr/bin/env bash
# Patch ProfileStacksPage persisted-query hash in GCS _code/pgql.tgz and reuse.tgz (VMs pull reuse.tgz each supervisor loop).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
NEW_HASH="${STACKS_PGQL_HASH:-bfdb9f435010690880e346cbebb518d06a853a0d7502b5081737540cf0b5db31}"
VM_GCS="${PACE_GCS_VM_ROOT:?}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
note="client-captured hash 2026-11-22 (verified @rrhoover Data Feeder)"
for pkg in pgql reuse; do
  src="${VM_GCS}/_code/${pkg}.tgz"
  "${GC[@]}" storage cp -q "$src" "$TMP/${pkg}.tgz"
  mkdir -p "$TMP/${pkg}"
  tar xzf "$TMP/${pkg}.tgz" -C "$TMP/${pkg}"
  OPS="$TMP/${pkg}/ops.json"
  [[ -f "$OPS" ]] || { echo "missing ops.json in $pkg" >&2; exit 1; }
  python3 - "$OPS" "$NEW_HASH" "$note" <<'PY'
import json, sys
path, h, note = sys.argv[1:4]
with open(path) as f:
    o = json.load(f)
st = o.get("ProfileStacksPage") or {}
old = st.get("hash", "")
if old == h:
    print(f"unchanged {path}")
else:
    st["hash"] = h
    st["note"] = note
    o["ProfileStacksPage"] = st
    with open(path, "w") as f:
        json.dump(o, f, indent=2)
        f.write("\n")
    print(f"patched {path} {old[:16]}.. -> {h[:16]}..")
PY
  tar czf "$TMP/${pkg}_new.tgz" -C "$TMP/${pkg}" .
  "${GC[@]}" storage cp -q "$TMP/${pkg}_new.tgz" "$src"
  md5=$(python3 -c 'import hashlib,base64,sys;print(base64.b64encode(hashlib.md5(open(sys.argv[1],"rb").read()).digest()).decode())' "$TMP/${pkg}_new.tgz")
  echo "published ${pkg}.tgz md5=${md5}"
done
echo "STACKS_PGQL_REPUBLISH_OK hash=${NEW_HASH}"