#!/usr/bin/env bash
# Startup script for usersim signup seed VMs.
#
# Runs as root on every boot. Idempotent. Mounts the durable identity disk and
# lays out the directories that accumulate human identity across studies:
#
#   /var/lib/usersim-seed/<seed-id>/
#     profiles/<host>/          Chrome profile per product (durable auth)
#     site_states/<host>.json   Playwright storage_state per product
#     secrets/                  env, sa.json, credentials.json, identities.json
#     chrome/                   legacy single-profile path (youtube seed compat)
#     state/health.json         seed health + auth state
#     logs/
#
# The boot disk is disposable; this disk is not.
set -euo pipefail

meta() {
  curl -sf -H 'Metadata-Flavor: Google' \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"
}

seed_id="$(meta seed-id)"
disk_name="$(meta seed-disk)"
mount=/var/lib/usersim-seed
root="$mount/$seed_id"

mkdir -p "$mount"
device="/dev/disk/by-id/google-${disk_name}"

# Wait for the attached data disk to appear before touching it — on cold boot the
# symlink can lag the startup script.
for _ in $(seq 1 30); do
  [[ -e "$device" ]] && break
  sleep 1
done

if ! mountpoint -q "$mount"; then
  if ! blkid "$device" >/dev/null 2>&1; then
    mkfs.ext4 -F "$device"
  fi
  mount "$device" "$mount"
  grep -q "usersim-seed" /etc/fstab \
    || echo "$device $mount ext4 defaults,nofail 0 2" >> /etc/fstab
fi

install -d -m 0700 "$root/chrome"
install -d -m 0700 "$root/profiles"
install -d -m 0700 "$root/secrets"
install -d -m 0755 "$root/site_states"
install -d -m 0755 "$root/state"
install -d -m 0755 "$root/logs"

# Preserve auth_state across reboots — a seed that has signed up for products
# must not be reported as uninitialized just because it rebooted.
health="$root/state/health.json"
if [[ ! -s "$health" ]]; then
  printf '{"seed_id":"%s","healthy":false,"auth_state":"uninitialized"}\n' "$seed_id" > "$health"
fi
chmod 0600 "$health"

touch /opt/usersim-seed-ready
