#!/usr/bin/env bash
# GCP Spot fleet for Gemini Browser Use bakeoff (full8 / full10 / full80 / full100).
#
# full8:   NUM_SHARDS=1  WORKERS=8  e2-standard-8  → 8 tasks, one VM
# full10:  NUM_SHARDS=3  WORKERS=4  → 10 tasks, ~8–12 min wall
# full80:  NUM_SHARDS=10 WORKERS=8  e2-standard-8  → 80 tasks
# full100: NUM_SHARDS=25 WORKERS=4  → 100 tasks, ~8–12 min wall (one wave)
#
# Each VM rejudges, uploads to GCS, and deletes itself when its shard is done
# (KEEP_VM=0 default), so the fleet costs nothing once the work is finished.
#
# Spot resume: each completed task checkpoints manifest+trace to GCS. Relaunch
# pulls that checkpoint before --resume so you continue mid-shard, not from zero.
#
# Usage:
#   STAGE=full10  ./scripts/vm/fleet_bakeoff.sh
#   STAGE=full80  ./scripts/vm/fleet_bakeoff.sh
#   STAGE=full100 ./scripts/vm/fleet_bakeoff.sh
#   ./scripts/vm/fleet_bakeoff.sh --status    # GCS done-markers, no SSH
#   ./scripts/vm/fleet_bakeoff.sh --pull      # GCS -> local, then merge
#   ./scripts/vm/fleet_bakeoff.sh --merge
#   ./scripts/vm/fleet_bakeoff.sh --down      # delete every fleet VM
#   ./scripts/vm/fleet_bakeoff.sh --relaunch  # restart preempted/missing shards;
#                                            # restores GCS checkpoints, skips finished tasks
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
# Optional single zone (disables round-robin). Otherwise GCP_ZONE_CANDIDATES is tried in order.
MACHINE="${GCP_MACHINE:-e2-standard-2}"
STAGE="${STAGE:-full10}"
WORKERS="${WORKERS:-4}"
MODEL="${GEMINI_MODEL:-gemini-2.5-flash-lite}"
TAG="${FLEET_TAG:-gemini-25-flash-lite_m60_fleet}"
# flash_mode strips evaluation_previous_goal / next_goal / thinking / planning from
# the agent schema. It cost 3 tasks on full10 and made agents burn the whole step
# budget, so it stays off unless explicitly requested.
FAST="${FAST:-0}"
ACTIONS_PER_STEP="${ACTIONS_PER_STEP:-3}"
DEPLOY_PARALLEL="${DEPLOY_PARALLEL:-10}"
GCS_PREFIX="${GCS_PREFIX:-gs://usersim-bakeoff-347838016394}"
RESUME="${RESUME:-1}"
KEEP_VM="${KEEP_VM:-0}"
# 0 = harness default (60). Set MAX_ACTIONS=33 to reproduce the old 12% baseline.
MAX_ACTIONS="${MAX_ACTIONS:-0}"
SKIP_KNOWN_BLOCKED="${SKIP_KNOWN_BLOCKED:-0}"
# Space-separated KEY=VALUE pairs forwarded to the shard, for arm-specific flags.
EXTRA_ENV="${EXTRA_ENV:-}"
EVAL_INDICES="${EVAL_INDICES:-}"

case "$STAGE" in
  full8)   NUM_SHARDS="${NUM_SHARDS:-1}";  PREFIX="${FLEET_PREFIX:-usersim-bu-f8}"; MACHINE="${GCP_MACHINE:-e2-standard-8}"; WORKERS="${WORKERS:-8}" ;;
  full10)  NUM_SHARDS="${NUM_SHARDS:-3}";  PREFIX="${FLEET_PREFIX:-usersim-bu-f10}" ;;
  full80)  NUM_SHARDS="${NUM_SHARDS:-10}"; PREFIX="${FLEET_PREFIX:-usersim-bu-f80}"; WORKERS="${WORKERS:-8}"; MACHINE="${GCP_MACHINE:-e2-standard-8}" ;;
  full100) NUM_SHARDS="${NUM_SHARDS:-25}"; PREFIX="${FLEET_PREFIX:-usersim-bu-f100}" ;;
  retry)   NUM_SHARDS="${NUM_SHARDS:-2}";  PREFIX="${FLEET_PREFIX:-usersim-bu-retry}" ;;
  *) echo "Unknown STAGE=$STAGE"; exit 1 ;;
esac

if [[ ! -f secrets/env ]]; then
  echo "ERROR: secrets/env missing"
  exit 1
fi
if [[ ! -f secrets/vertex_adc.json ]]; then
  echo "ERROR: secrets/vertex_adc.json missing (copy gcloud legacy adc for judge)"
  exit 1
fi

gcloud config set account shreyas.patel@searce.com 2>/dev/null || true

merge_shards() {
  PYTHONPATH=src python3 - <<PY
import json
from pathlib import Path
from capability.metrics import sort_runs, summarize

stage = "${STAGE}"
tag = "${TAG}"
out_dir = Path("results/capability")
shards = sorted(out_dir.glob(f"{stage}_browser_use_{tag}_shard*.json"))
if not shards:
    shards = sorted(out_dir.glob(f"{stage}_browser_use_*_fleet_shard*.json"))
if not shards:
    raise SystemExit("No shard files found in results/capability/")
runs = []
for p in shards:
    runs.extend(json.loads(p.read_text()).get("runs") or [])
merged_name = {
    "full8": f"full8_browser_use_{tag}.json",
    "full10": f"full10_browser_use_{tag}.json",
    "full80": f"full80_browser_use_{tag}.json",
    "full100": f"full100_browser_use_{tag}.json",
}.get(stage, f"{stage}_browser_use_{tag}.json")
merged = out_dir / merged_name
base = json.loads(shards[0].read_text())
base.update(summarize(runs))
base["runs"] = sort_runs(runs)
base["fleet_shards"] = [p.name for p in shards]
merged.write_text(json.dumps(base, indent=2, default=str))
print(f"Merged {len(shards)} shards -> {merged.name} ({len(runs)} runs)")
s = summarize(runs)
print(f"success_rate_scored={s.get('success_rate_scored')}  n_scored={s.get('n_scored')}/{s.get('n')}")
PY
}

rejudge_local() {
  PYTHONPATH=src python3 - <<'PY'
import json
from pathlib import Path
from capability.rejudge import rejudge_run
from capability.metrics import sort_runs, summarize

out_dir = Path("results/capability")
for p in sorted(out_dir.glob("*_fleet_shard*.json")):
    payload = json.loads(p.read_text())
    runs = payload.get("runs") or []
    changed = 0
    for run in runs:
        if run.get("status") not in ("JUDGE_ERROR", "AMBIGUOUS"):
            continue
        # Fix VM trace paths -> local if traces were pulled
        td = run.get("trace_dir") or ""
        if td.startswith("/home/"):
            idx = run.get("eval_index")
            local = out_dir / "traces" / f"bu_{idx}_fleet"
            if local.is_dir():
                run["trace_dir"] = str(local)
        before = run.get("status")
        run, flipped = rejudge_run(run)
        changed += int(flipped or run.get("status") != before)
    payload.update(summarize(runs))
    payload["runs"] = sort_runs(runs)
    p.write_text(json.dumps(payload, indent=2, default=str))
    s = summarize(runs)
    print(f"{p.name}: success_rate_scored={s.get('success_rate_scored')} judge_errors={s.get('by_status',{}).get('JUDGE_ERROR',0)}")
PY
}

DEST_GCS="${GCS_PREFIX}/${STAGE}/${TAG}"
MANIFEST_BASENAME="${STAGE}_browser_use_${TAG}"

# Tasks each shard should finish (used for done-marker validation + relaunch).
TASKS_PER_SHARD=$(PYTHONPATH=src python3 <<PY
import os
from capability.tasks import (
    ALL_INDICES, BAKEOFF5_INDICES, FULL8_INDICES, FULL80_INDICES,
    SMOKE_INDICES, TASK_INDICES,
)
stage = os.environ.get("STAGE", "full10")
num = int(os.environ.get("NUM_SHARDS", "1"))
if stage == "smoke":
    n = len(SMOKE_INDICES)
elif stage == "bakeoff5":
    n = len(BAKEOFF5_INDICES)
elif stage == "full8":
    n = len(FULL8_INDICES)
elif stage == "full10":
    n = len(TASK_INDICES)
elif stage == "full80":
    n = len(FULL80_INDICES)
elif stage == "full100":
    n = len(ALL_INDICES)
else:
    n = num
print((n + num - 1) // num)
PY
)
export TASKS_PER_SHARD

# --- Zone round-robin (Spot stockouts are per-zone, not project quota) ---
ZONE_CANDIDATES_ARR=()
ZONE_CACHE_DIR=""

parse_zone_candidates() {
  ZONE_CANDIDATES_ARR=()
  if [[ -n "${GCP_ZONE:-}" ]]; then
    ZONE_CANDIDATES_ARR=("$GCP_ZONE")
    return
  fi
  local raw="${GCP_ZONE_CANDIDATES:-us-central1-a,us-central1-b,us-central1-c,us-central1-f}"
  local part
  IFS=',' read -ra _parts <<< "$raw"
  for part in "${_parts[@]}"; do
    part="${part//[[:space:]]/}"
    [[ -n "$part" ]] && ZONE_CANDIDATES_ARR+=("$part")
  done
  if ((${#ZONE_CANDIDATES_ARR[@]} == 0)); then
    echo "ERROR: no zones in GCP_ZONE_CANDIDATES" >&2
    exit 1
  fi
}

init_zone_cache() {
  ZONE_CACHE_DIR="${ROOT}/results/capability/fleet_zones/${PREFIX}_${TAG}"
  mkdir -p "$ZONE_CACHE_DIR"
}

shard_zone_cache_file() {
  echo "${ZONE_CACHE_DIR}/shard${1}.zone"
}

save_shard_zone() {
  echo "$2" > "$(shard_zone_cache_file "$1")"
}

read_shard_zone_cache() {
  local f
  f="$(shard_zone_cache_file "$1")"
  [[ -f "$f" ]] && tr -d '[:space:]' < "$f" || true
}

# Locate an existing fleet VM across candidate zones (updates cache).
find_shard_zone() {
  local i="$1"
  local name="${PREFIX}-${i}"
  local z cached
  cached=$(read_shard_zone_cache "$i")
  if [[ -n "$cached" ]]; then
    if gcloud compute instances describe "$name" --zone="$cached" --project="$PROJECT" &>/dev/null; then
      echo "$cached"
      return 0
    fi
  fi
  for z in "${ZONE_CANDIDATES_ARR[@]}"; do
    if gcloud compute instances describe "$name" --zone="$z" --project="$PROJECT" &>/dev/null; then
      save_shard_zone "$i" "$z"
      echo "$z"
      return 0
    fi
  done
  return 1
}

is_zone_stockout_error() {
  local log="$1"
  grep -qiE 'ZONE_RESOURCE_POOL_EXHAUSTED|stockout|does not have enough resources' "$log"
}

# Create Spot VM in candidate zones, round-robin start index = shard id.
create_shard_vm() {
  local i="$1"
  local name="${PREFIX}-${i}"
  local n=${#ZONE_CANDIDATES_ARR[@]}
  local start=$((i % n))
  local offset z log
  log="/tmp/gcloud-create-${PREFIX}-${i}-$$.log"
  for offset in $(seq 0 $((n - 1))); do
    z="${ZONE_CANDIDATES_ARR[$(( (start + offset) % n ))]}"
    echo "    Trying ${name} (${MACHINE}) in ${z}..."
    if gcloud compute instances create "$name" \
        --project="$PROJECT" --zone="$z" \
        --machine-type="$MACHINE" \
        --provisioning-model=SPOT \
        --instance-termination-action=STOP \
        --boot-disk-size=30GB --boot-disk-type=pd-balanced \
        --network=main-vpc --subnet=primary-subnet \
        --scopes=cloud-platform \
        --tags=allow-iap-ssh \
        --quiet 2>"$log"; then
      save_shard_zone "$i" "$z"
      echo "    Created ${name} in ${z}"
      rm -f "$log"
      return 0
    fi
    if is_zone_stockout_error "$log"; then
      echo "    ${z}: no capacity (stockout), trying next zone..."
      rm -f "$log"
      continue
    fi
    echo "    ${z}: create failed:" >&2
    tail -5 "$log" >&2 || true
    rm -f "$log"
    return 1
  done
  echo "    ERROR: no zone had Spot capacity for ${name} (tried: ${ZONE_CANDIDATES_ARR[*]})" >&2
  return 1
}

parse_zone_candidates
init_zone_cache

# Status and pull go through GCS. The old versions walked every VM over IAP
# serially, which took minutes for a 25-shard fleet and usually timed out.
fleet_status() {
  local done_n complete_n
  done_n=$(gcloud storage ls "${DEST_GCS}/_done/**" 2>/dev/null | grep -c '\.done$' || true)
  complete_n=0
  for i in $(seq 0 $((NUM_SHARDS - 1))); do
    if shard_complete_in_gcs "$i"; then
      ((complete_n++)) || true
    fi
  done
  echo "complete: ${complete_n:-0}/${NUM_SHARDS} shards (manifest + exit=0)"
  echo "done markers: ${done_n:-0} (may include failed/stale)"
  echo "tasks/shard: ${TASKS_PER_SHARD}  (${DEST_GCS})"
  echo ""
  gcloud compute instances list --project="$PROJECT" \
    --filter="name~^${PREFIX}-[0-9]+$" --format='table(name,status,zone,machineType.basename())' 2>/dev/null || true
}

pull_shards() {
  mkdir -p results/capability
  gcloud storage cp "${DEST_GCS}/manifests/*.json" results/capability/ --quiet 2>/dev/null \
    || echo "    no manifests in GCS yet"
}

pull_traces() {
  mkdir -p results/capability/traces
  gcloud storage cp --recursive "${DEST_GCS}/traces/*" results/capability/traces/ \
    --quiet 2>/dev/null || true
}

fleet_down() {
  local rows name zone
  rows=$(gcloud compute instances list --project="$PROJECT" \
    --filter="name~^${PREFIX}-[0-9]+$" --format="value(name,zone)" 2>/dev/null || true)
  if [[ -z "$rows" ]]; then
    echo "no ${PREFIX} instances left"
    return 0
  fi
  while read -r name zone; do
    [[ -z "$name" ]] && continue
    echo "deleting ${name} (${zone})"
    gcloud compute instances delete "$name" --zone="$zone" --project="$PROJECT" --quiet
  done <<< "$rows"
}

shard_done_in_gcs() {
  local i="$1"
  gcloud storage ls "${DEST_GCS}/_done/shard${i}.done" &>/dev/null
}

shard_manifest_in_gcs() {
  local i="$1"
  gcloud storage ls "${DEST_GCS}/manifests/${MANIFEST_BASENAME}_shard${i}.json" &>/dev/null
}

# Done marker alone is not enough — shard 6 uploaded exit=1 with no manifest.
shard_complete_in_gcs() {
  local i="$1"
  local tmp="/tmp/shard${i}.done.$$"
  if ! gcloud storage cp "${DEST_GCS}/_done/shard${i}.done" "$tmp" --quiet 2>/dev/null; then
    return 1
  fi
  if ! grep -q '^exit=0$' "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  rm -f "$tmp"
  shard_manifest_in_gcs "$i"
}

shard_cleanup_stale_done() {
  local i="$1"
  if shard_done_in_gcs "$i" && ! shard_complete_in_gcs "$i"; then
    echo "    Removing stale done marker (shard $i: missing manifest or exit!=0)"
    gcloud storage rm "${DEST_GCS}/_done/shard${i}.done" --quiet 2>/dev/null || true
  fi
}

# A preempted VM that GCP brings back reports RUNNING with no work on it, so
# instance status alone is not evidence the shard is alive. Ask the box.
shard_process_alive() {
  local i="$1"
  local name="${PREFIX}-${i}"
  local zone out
  zone=$(find_shard_zone "$i") || return 1
  out=$(gcloud compute ssh "$name" --zone="$zone" --project="$PROJECT" \
    --tunnel-through-iap --quiet --command="pgrep -f '[s]hard_runner.sh' >/dev/null && echo ALIVE || echo DEAD" \
    2>/dev/null | tr -d '[:space:]')
  [[ "$out" == *ALIVE* ]]
}

ensure_shard_vm() {
  local i="$1"
  local name="${PREFIX}-${i}"
  local zone status cur_mt
  zone=$(find_shard_zone "$i") || true
  if [[ -n "$zone" ]]; then
    cur_mt=$(gcloud compute instances describe "$name" --zone="$zone" --project="$PROJECT" \
      --format='value(machineType)' 2>/dev/null || echo "")
    if [[ -n "$cur_mt" && "$cur_mt" != *"/${MACHINE}" ]]; then
      echo "    ${name} in ${zone}: wrong machine (${cur_mt##*/} != ${MACHINE}), recreating..."
      gcloud compute instances delete "$name" --zone="$zone" --project="$PROJECT" --quiet
      zone=""
      sleep 5
    fi
  fi
  if [[ -z "$zone" ]]; then
    create_shard_vm "$i" || return 1
    zone=$(find_shard_zone "$i")
    sleep 20
  fi
  status=$(gcloud compute instances describe "$name" --zone="$zone" --project="$PROJECT" \
    --format='value(status)' 2>/dev/null || echo UNKNOWN)
  if [[ "$status" != "RUNNING" ]]; then
    echo "    Starting ${name} in ${zone} (was ${status})..."
    if ! gcloud compute instances start "$name" --zone="$zone" --project="$PROJECT" --quiet 2>/tmp/start-${i}.log; then
      if is_zone_stockout_error "/tmp/start-${i}.log"; then
        echo "    ${zone}: start stockout, recreating in another zone..."
        gcloud compute instances delete "$name" --zone="$zone" --project="$PROJECT" --quiet 2>/dev/null || true
        rm -f "$(shard_zone_cache_file "$i")"
        create_shard_vm "$i" || return 1
        zone=$(find_shard_zone "$i")
        sleep 15
      else
        return 1
      fi
    else
      sleep 15
    fi
  fi
}

fleet_relaunch() {
  echo "==> Relaunch missing/preempted shards (${DEST_GCS})"
  TARBALL="/tmp/usersim-fleet-relaunch-$$.tgz"
  tar czf "$TARBALL" -C "$ROOT" src data scripts/vm/shard_runner.sh \
    secrets/env secrets/vertex_adc.json
  local relaunch=()
  for i in $(seq 0 $((NUM_SHARDS - 1))); do
    shard_cleanup_stale_done "$i"
    if shard_complete_in_gcs "$i"; then
      echo "  shard $i: complete (GCS)"
      continue
    fi
    local name="${PREFIX}-${i}"
    local status=MISSING zone
    zone=$(find_shard_zone "$i") || true
    if [[ -n "$zone" ]]; then
      status=$(gcloud compute instances describe "$name" --zone="$zone" --project="$PROJECT" \
        --format='value(status)' 2>/dev/null || echo UNKNOWN)
    fi
    if [[ "$status" == "RUNNING" ]] && shard_process_alive "$i"; then
      echo "  shard $i: still running"
      continue
    fi
    if [[ "$status" == "RUNNING" ]]; then
      echo "  shard $i: VM up but no shard_runner process — redeploying"
    else
      echo "  shard $i: relaunch (${status})"
    fi
    ensure_shard_vm "$i"
    relaunch+=("$i")
  done
  if ((${#relaunch[@]} == 0)); then
    rm -f "$TARBALL"
    echo "==> Nothing to relaunch."
    return 0
  fi
  echo "==> Deploying ${#relaunch[@]} shard(s): ${relaunch[*]}"
  for i in "${relaunch[@]}"; do
    install_and_run_shard "$i" &
    if (( i % DEPLOY_PARALLEL == DEPLOY_PARALLEL - 1 )); then wait; fi
  done
  wait
  rm -f "$TARBALL"
  echo "==> Relaunch complete."
}

install_and_run_shard() {
  local i="$1"
  local name="${PREFIX}-${i}"
  local zone attempt ok=0
  zone=$(find_shard_zone "$i") || {
    echo "    ERROR: shard $i has no VM zone (create failed?)"
    return 1
  }
  for attempt in 1 2 3; do
    if gcloud compute scp "$TARBALL" "${name}:~/usersim.tgz" \
      --zone="$zone" --project="$PROJECT" --tunnel-through-iap --quiet \
      && gcloud compute ssh "$name" --zone="$zone" --project="$PROJECT" --tunnel-through-iap --quiet \
      --command="set -eux
mkdir -p ~/usersim && cd ~/usersim
rm -rf src data scripts secrets    # keep .venv so warm VMs skip the 90s install
tar xzf ~/usersim.tgz -C ~/usersim
if [[ ! -d .venv ]]; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip
  python3 -m venv .venv
  .venv/bin/pip install -q -U pip wheel
  .venv/bin/pip install -q 'browser-use==0.13.8' playwright google-genai google-auth httpx pydantic PyYAML requests tenacity browserbase openai
  .venv/bin/playwright install chromium
  sudo .venv/bin/playwright install-deps chromium 2>/dev/null || true
fi
chmod +x scripts/vm/shard_runner.sh
nohup env \
  STAGE=${STAGE} TAG=${TAG} SHARD_ID=${i} NUM_SHARDS=${NUM_SHARDS} \
  MODEL=${MODEL} WORKERS=${WORKERS} GCS_PREFIX=${GCS_PREFIX} \
  FAST=${FAST} ACTIONS_PER_STEP=${ACTIONS_PER_STEP} \
  RESUME=${RESUME} KEEP_VM=${KEEP_VM} MAX_ACTIONS=${MAX_ACTIONS} \
  SKIP_KNOWN_BLOCKED=${SKIP_KNOWN_BLOCKED} EXPECTED_TASKS=${TASKS_PER_SHARD} \
  EVAL_INDICES='${EVAL_INDICES}' \
  EXTRA_ENV='${EXTRA_ENV}' \
  bash scripts/vm/shard_runner.sh > ~/bakeoff_shard${i}.log 2>&1 &
echo STARTED_${STAGE}_SHARD_${i}
"; then
      ok=1
      break
    fi
    echo "    deploy shard $i attempt $attempt failed, retrying in 30s..."
    sleep 30
  done
  if [[ "$ok" != "1" ]]; then
    echo "    ERROR: deploy shard $i failed after 3 attempts"
    return 1
  fi
}

case "${1:-}" in
  --merge)  merge_shards; exit 0 ;;
  --status) fleet_status; exit 0 ;;
  --pull)   pull_shards; merge_shards; exit 0 ;;
  --traces) pull_traces; exit 0 ;;
  --down)   fleet_down; exit 0 ;;
  --relaunch) fleet_relaunch; exit 0 ;;
  --rejudge) rejudge_local; merge_shards; exit 0 ;;
esac

echo "==> Fleet ${STAGE}: ${NUM_SHARDS}× ${MACHINE} @ workers=${WORKERS}"
echo "    zones: ${ZONE_CANDIDATES_ARR[*]} (round-robin per shard; override with GCP_ZONE or GCP_ZONE_CANDIDATES)"

TARBALL="/tmp/usersim-fleet-$$.tgz"
tar czf "$TARBALL" -C "$ROOT" src data scripts/vm/shard_runner.sh \
  secrets/env secrets/vertex_adc.json

for i in $(seq 0 $((NUM_SHARDS - 1))); do
  ensure_shard_vm "$i" &
  if (( i % DEPLOY_PARALLEL == DEPLOY_PARALLEL - 1 )); then wait; fi
done
wait

echo "==> Waiting 25s for VMs to accept SSH before deploy..."
sleep 25

echo "==> Deploying shards (parallel batches of ${DEPLOY_PARALLEL})..."
for i in $(seq 0 $((NUM_SHARDS - 1))); do
  install_and_run_shard "$i" &
  if (( i % DEPLOY_PARALLEL == DEPLOY_PARALLEL - 1 )); then wait; fi
done
wait
rm -f "$TARBALL"

echo ""
echo "==> ${STAGE} fleet launched on ${NUM_SHARDS} VMs."
echo "    Each VM rejudges, uploads to ${DEST_GCS}, then deletes itself."
echo "    Status: STAGE=${STAGE} ./scripts/vm/fleet_bakeoff.sh --status"
echo "    Pull:   STAGE=${STAGE} ./scripts/vm/fleet_bakeoff.sh --pull"
echo "    Down:   STAGE=${STAGE} ./scripts/vm/fleet_bakeoff.sh --down"
