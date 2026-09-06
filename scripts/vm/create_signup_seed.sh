#!/usr/bin/env bash
# Create a signup-enabled seed VM, modelled on usersim-youtube-seed-*.
#
# A seed is a standing VM with a durable identity disk. Chrome profiles and
# storage states accumulate on that disk, so authenticated products survive
# reboots, re-provisioning, and boot-disk replacement. Signup happens once per
# product per seed; every later study reuses the session.
#
# Faithful to the youtube seed on the parts that matter:
#   - dedicated VPC (usersim-seed-network) with Cloud NAT on pinned static IPs,
#     so egress identity is stable rather than a random datacenter address
#   - separate pd-balanced identity disk mounted at /var/lib/usersim-seed
#   - seed-id / seed-disk / usersim-seed-independent metadata contract
#   - STANDARD provisioning (not Spot) — a seed must not vanish mid-study
#
# Differs deliberately:
#   - Ubuntu 24.04 instead of Debian 12, to reuse the proven signup bootstrap
#   - its own static egress IP, so signup traffic is not judged on the IP the
#     youtube seeds have been hammering
#   - service account attached, so Vertex works without shipping a key
#   - product-agnostic profile layout instead of a single youtube profile
#
# Usage:
#   scripts/vm/create_signup_seed.sh                 # seed 0
#   SEED_INDEX=1 scripts/vm/create_signup_seed.sh    # replicate as seed 1
#
# Env:
#   SEED_INDEX=0            which seed to create/refresh
#   SEED_PREFIX=usersim-signup-seed
#   ZONE=us-central1-a      must be in us-central1 (seed subnet is regional)
#   MACHINE=e2-standard-8
#   DISK_SIZE=30
#   NEW_EGRESS=1            allocate + attach a dedicated NAT egress IP
#   SKIP_PROVISION=0        create infra only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
ZONE="${ZONE:-us-central1-a}"
REGION="${ZONE%-*}"
MACHINE="${MACHINE:-e2-standard-8}"
DISK_SIZE="${DISK_SIZE:-30}"
SEED_INDEX="${SEED_INDEX:-0}"
SEED_PREFIX="${SEED_PREFIX:-usersim-signup-seed}"
NEW_EGRESS="${NEW_EGRESS:-1}"
SKIP_PROVISION="${SKIP_PROVISION:-0}"

NAME="${SEED_PREFIX}-${SEED_INDEX}"
DISK="${NAME}-identity"
EGRESS_ADDR="${SEED_PREFIX}-egress-${SEED_INDEX}"
NETWORK="${SEED_NETWORK:-usersim-seed-network}"
SUBNET="${SEED_SUBNET:-usersim-seed-subnet}"
ROUTER="${SEED_ROUTER:-usersim-seed-router}"
NAT="${SEED_NAT:-usersim-seed-nat}"

# Non-interactive gcloud when a key is present.
if [[ -f "$ROOT/secrets/sa.json" ]]; then
  export CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE="${CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE:-$ROOT/secrets/sa.json}"
  export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-$ROOT/secrets/sa.json}"
  SA_EMAIL="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("client_email",""))' "$ROOT/secrets/sa.json" 2>/dev/null || true)"
else
  SA_EMAIL=""
fi

G=(gcloud --quiet "--project=$PROJECT")
SSH=("${G[@]}" compute ssh "$NAME" "--zone=$ZONE" --tunnel-through-iap)
SCP=("${G[@]}" compute scp "--zone=$ZONE" --tunnel-through-iap)

echo "==> seed ${NAME} (${MACHINE}, ${ZONE}) on ${NETWORK}"

# ---- 1. dedicated egress IP -------------------------------------------------
# A signup seed needs a stable public identity of its own. The youtube seeds get
# this from Cloud NAT's MANUAL_ONLY pool, but a shared pool does not pin one IP
# per VM — with endpoint-independent mapping off, connections spread across all
# pool IPs. So signup traffic would be judged on IPs the youtube seeds have been
# hammering for a week.
#
# Attaching the static address directly to the NIC bypasses NAT and gives this
# seed one deterministic egress IP. Inbound stays closed: the only ingress rule
# on this VPC is IAP SSH from 35.235.240.0/20, and default-deny covers the rest.
if [[ "$NEW_EGRESS" == "1" ]]; then
  if ! "${G[@]}" compute addresses describe "$EGRESS_ADDR" --region="$REGION" >/dev/null 2>&1; then
    echo "==> allocating egress IP ${EGRESS_ADDR}"
    "${G[@]}" compute addresses create "$EGRESS_ADDR" --region="$REGION"
  fi
  EGRESS_IP="$("${G[@]}" compute addresses describe "$EGRESS_ADDR" --region="$REGION" --format='value(address)')"
  echo "    dedicated egress IP ${EGRESS_IP} (own IP, not the shared NAT pool)"
fi

# ---- 2. identity disk -------------------------------------------------------
# Created independently of the VM and never auto-deleted. This disk is the seed.
if ! "${G[@]}" compute disks describe "$DISK" --zone="$ZONE" >/dev/null 2>&1; then
  echo "==> creating identity disk ${DISK} (${DISK_SIZE}GB)"
  "${G[@]}" compute disks create "$DISK" \
    --zone="$ZONE" --size="${DISK_SIZE}GB" --type=pd-balanced \
    --labels=role=usersim-seed-identity,seed="${NAME}"
else
  echo "    identity disk ${DISK} exists — reusing (accounts preserved)"
fi

# ---- 3. the VM --------------------------------------------------------------
if ! "${G[@]}" compute instances describe "$NAME" --zone="$ZONE" >/dev/null 2>&1; then
  echo "==> creating VM ${NAME}"
  CREATE=(
    "${G[@]}" compute instances create "$NAME"
    "--zone=$ZONE"
    "--machine-type=$MACHINE"
    --image-family=ubuntu-2404-lts-amd64
    --image-project=ubuntu-os-cloud
    --boot-disk-size=40GB
    --boot-disk-type=pd-balanced
    "--network=$NETWORK"
    "--subnet=$SUBNET"
    --tags=allow-iap-ssh
    "--disk=name=$DISK,device-name=$DISK,mode=rw,auto-delete=no"
    "--metadata=seed-id=$NAME,seed-disk=$DISK,usersim-seed-independent=true,seed-role=signup"
    "--metadata-from-file=startup-script=$ROOT/scripts/vm/seed_startup.sh"
    --labels=role=usersim-seed,seed-role=signup
  )
  if [[ "$NEW_EGRESS" == "1" ]]; then
    CREATE+=("--address=$EGRESS_ADDR")
  else
    CREATE+=(--no-address)
  fi
  if [[ -n "$SA_EMAIL" ]]; then
    CREATE+=("--service-account=$SA_EMAIL" --scopes=cloud-platform)
  else
    CREATE+=(--scopes=cloud-platform)
  fi
  "${CREATE[@]}"
else
  STATUS="$("${G[@]}" compute instances describe "$NAME" --zone="$ZONE" --format='value(status)')"
  echo "    VM exists (${STATUS})"
  if [[ "$STATUS" != "RUNNING" ]]; then
    echo "==> starting ${NAME}"
    "${G[@]}" compute instances start "$NAME" --zone="$ZONE"
  fi
fi

if [[ "$SKIP_PROVISION" == "1" ]]; then
  echo "==> SKIP_PROVISION=1 — infra ready, stopping here"
  exit 0
fi

# ---- 4. wait for IAP SSH ----------------------------------------------------
echo "==> waiting for SSH"
for i in $(seq 1 60); do
  if "${SSH[@]}" --command='echo up' >/dev/null 2>&1; then
    echo "    ssh up after ${i} tries"
    break
  fi
  sleep 5
  if [[ "$i" == 60 ]]; then echo "FATAL: SSH never came up" >&2; exit 1; fi
done

# ---- 5. ship code + secrets -------------------------------------------------
echo "==> packing payload"
TAR="$(mktemp -t usersim-seed-XXXX).tgz"
tar -czf "$TAR" \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' \
  --exclude='mvp/runs' --exclude='node_modules' \
  pyproject.toml src mvp scripts/vm scripts/local \
  $([[ -f secrets/env ]] && echo secrets/env) \
  $([[ -f secrets/sa.json ]] && echo secrets/sa.json) \
  $([[ -f secrets/credentials.json ]] && echo secrets/credentials.json) \
  $([[ -f secrets/identities.json ]] && echo secrets/identities.json)

"${SSH[@]}" --command='rm -rf ~/usersim && mkdir -p ~/usersim'
"${SCP[@]}" "$TAR" "$NAME:~/usersim/payload.tgz"
rm -f "$TAR"
"${SSH[@]}" --command='cd ~/usersim && tar xzf payload.tgz && rm -f payload.tgz'

echo "==> provisioning (apt + venv + chromium, ~5-8 min)"
"${SSH[@]}" --command='stdbuf -oL -eL bash ~/usersim/scripts/vm/seed_provision.sh 2>&1'

echo
echo "==> seed health"
"${SSH[@]}" --command="cat /var/lib/usersim-seed/${NAME}/state/health.json"

cat <<EOF

Seed ready: ${NAME}
  ssh:      gcloud compute ssh ${NAME} --zone=${ZONE} --tunnel-through-iap --project=${PROJECT}
  identity: /var/lib/usersim-seed/${NAME}   (disk ${DISK}, survives VM deletion)
  replicate: SEED_INDEX=$((SEED_INDEX + 1)) scripts/vm/create_signup_seed.sh
EOF
