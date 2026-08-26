#!/usr/bin/env bash
# GCP Spot fleet for Mistral bakeoff (full8 / full10 / full80 / full100).
#
# full8:   NUM_SHARDS=1  WORKERS=8  e2-standard-8  → 8 tasks, one VM
# full10:  NUM_SHARDS=3  WORKERS=4  → 10 tasks, ~8–12 min wall
# full80:  NUM_SHARDS=10 WORKERS=8  e2-standard-8  → 80 tasks, ~10–15 min wall
# full100: NUM_SHARDS=25 WORKERS=4  → 100 tasks, ~8–12 min wall (one wave)
#
# Each VM rejudges, uploads to GCS, and deletes itself when its shard is done,
# so the fleet costs nothing once the work is finished and status checks never
# need SSH.
#
# Usage:
#   STAGE=full10  ./scripts/vm/fleet_bakeoff.sh
#   STAGE=full100 ./scripts/vm/fleet_bakeoff.sh
#   ./scripts/vm/fleet_bakeoff.sh --status    # GCS done-markers, no SSH
#   ./scripts/vm/fleet_bakeoff.sh --pull      # GCS -> local, then merge
#   ./scripts/vm/fleet_bakeoff.sh --merge
#   ./scripts/vm/fleet_bakeoff.sh --down      # delete every fleet VM
#   ./scripts/vm/fleet_bakeoff.sh --relaunch  # restart preempted/missing shards;
#                                            # restores GCS checkpoints, skips finished tasks
# Spot resume: each completed task checkpoints manifest+trace to GCS. Relaunch
# pulls that checkpoint before --resume so you continue mid-shard, not from zero.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
ZONE="${GCP_ZONE:-us-central1-a}"
MACHINE="${GCP_MACHINE:-e2-standard-2}"
STAGE="${STAGE:-full10}"
WORKERS="${WORKERS:-4}"
MODEL="${MISTRAL_MODEL:-mistral-small-2603}"
TAG="${FLEET_TAG:-mistral-small-2603_m33_stage1_fleet}"
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
# Space-separated KEY=VALUE pairs forwarded to the shard, for arm-specific flags.
EXTRA_ENV="${EXTRA_ENV:-}"
EVAL_INDICES="${EVAL_INDICES:-}"

case "$STAGE" in
  full8)   NUM_SHARDS="${NUM_SHARDS:-1}";  PREFIX="${FLEET_PREFIX:-usersim-bu-f8}" ;;
  full10)  NUM_SHARDS="${NUM_SHARDS:-3}";  PREFIX="${FLEET_PREFIX:-usersim-bu-f10}" ;;
  full80)  NUM_SHARDS="${NUM_SHARDS:-10}"; PREFIX="${FLEET_PREFIX:-usersim-bu-f80}" ;;
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
shards = sorted(out_dir.glob(f"{stage}_mistral_{tag}_shard*.json"))
if not shards:
    shards = sorted(out_dir.glob(f"{stage}_mistral_*_fleet_shard*.json"))
if not shards:
    raise SystemExit("No shard files found in results/capability/")
runs = []
for p in shards:
    runs.extend(json.loads(p.read_text()).get("runs") or [])
merged_name = {
    "full8": f"full8_mistral_{tag}.json",
    "full10": "full10_mistral_mistral-small-2603_m33_stage1_fleet.json",
    "full80": f"full80_mistral_{tag}.json",
    "full100": "full100_mistral_mistral-small-2603_m33_stage1_fleet.json",
}.get(stage, f"{stage}_mistral_{tag}.json")
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
            local = out_dir / "traces" / f"mistral_{idx}_fleet"
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

# Status and pull go through GCS. The old versions walked every VM over IAP
# serially, which took minutes for a 25-shard fleet and usually timed out.
fleet_status() {
  local done_n
  done_n=$(gcloud storage ls "${DEST_GCS}/_done/**" 2>/dev/null | grep -c '\.done$' || true)
  echo "reported: ${done_n:-0}/${NUM_SHARDS} shards  (${DEST_GCS})"
  echo ""
  gcloud compute instances list --project="$PROJECT" \
    --filter="name~^${PREFIX}-[0-9]+$" --format='table(name,status)' 2>/dev/null || true
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
  local names
  names=$(gcloud compute instances list --project="$PROJECT" \
    --filter="name~^${PREFIX}-[0-9]+$" --format='value(name)' 2>/dev/null || true)
  if [[ -z "$names" ]]; then
    echo "no ${PREFIX} instances left"
    return 0
  fi
  echo "deleting: $(echo "$names" | tr '\n' ' ')"
  # One batched call; gcloud deletes these concurrently.
  # shellcheck disable=SC2086
  gcloud compute instances delete $names --zone="$ZONE" --project="$PROJECT" --quiet
}

shard_done_in_gcs() {
  local i="$1"
  gcloud storage ls "${DEST_GCS}/_done/shard${i}.done" &>/dev/null
}

# A preempted VM that GCP brings back reports RUNNING with no work on it, so
# instance status alone is not evidence the shard is alive. Ask the box.
shard_process_alive() {
  local i="$1"
  local name="${PREFIX}-${i}"
  local out
  out=$(gcloud compute ssh "$name" --zone="$ZONE" --project="$PROJECT" \
    --tunnel-through-iap --quiet --command="pgrep -f '[s]hard_runner.sh' >/dev/null && echo ALIVE || echo DEAD" \
    2>/dev/null | tr -d '[:space:]')
  [[ "$out" == *ALIVE* ]]
}

ensure_shard_vm() {
  local i="$1"
  local name="${PREFIX}-${i}"
  if ! gcloud compute instances describe "$name" --zone="$ZONE" --project="$PROJECT" &>/dev/null; then
    echo "    Creating ${name}..."
    gcloud compute instances create "$name" \
      --project="$PROJECT" --zone="$ZONE" \
      --machine-type="$MACHINE" \
      --provisioning-model=SPOT \
      --instance-termination-action=STOP \
      --boot-disk-size=30GB --boot-disk-type=pd-balanced \
      --network=main-vpc --subnet=primary-subnet \
      --scopes=cloud-platform \
      --tags=allow-iap-ssh \
      --quiet
    return 0
  fi
  local status
  status=$(gcloud compute instances describe "$name" --zone="$ZONE" --project="$PROJECT" \
    --format='value(status)' 2>/dev/null || echo UNKNOWN)
  if [[ "$status" != "RUNNING" ]]; then
    echo "    Starting ${name} (was ${status})..."
    gcloud compute instances start "$name" --zone="$ZONE" --project="$PROJECT" --quiet
    sleep 10
  fi
}

fleet_relaunch() {
  echo "==> Relaunch missing/preempted shards (${DEST_GCS})"
  TARBALL="/tmp/usersim-fleet-relaunch-$$.tgz"
  tar czf "$TARBALL" -C "$ROOT" src data scripts/vm/shard_runner.sh \
    secrets/env secrets/vertex_adc.json
  local relaunch=()
  for i in $(seq 0 $((NUM_SHARDS - 1))); do
    if shard_done_in_gcs "$i"; then
      echo "  shard $i: done (GCS)"
      continue
    fi
    local name="${PREFIX}-${i}"
    local status=MISSING
    if gcloud compute instances describe "$name" --zone="$ZONE" --project="$PROJECT" &>/dev/null; then
      status=$(gcloud compute instances describe "$name" --zone="$ZONE" --project="$PROJECT" \
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
  gcloud compute scp "$TARBALL" "${name}:~/usersim.tgz" \
    --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --quiet
  gcloud compute ssh "$name" --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --quiet \
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
  EVAL_INDICES='${EVAL_INDICES}' \
  EXTRA_ENV='${EXTRA_ENV}' \
  bash scripts/vm/shard_runner.sh > ~/bakeoff_shard${i}.log 2>&1 &
echo STARTED_${STAGE}_SHARD_${i}
"
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

TARBALL="/tmp/usersim-fleet-$$.tgz"
tar czf "$TARBALL" -C "$ROOT" src data scripts/vm/shard_runner.sh \
  secrets/env secrets/vertex_adc.json

for i in $(seq 0 $((NUM_SHARDS - 1))); do
  name="${PREFIX}-${i}"
  if ! gcloud compute instances describe "$name" --zone="$ZONE" --project="$PROJECT" &>/dev/null; then
    echo "    Creating ${name}..."
    gcloud compute instances create "$name" \
      --project="$PROJECT" --zone="$ZONE" \
      --machine-type="$MACHINE" \
      --provisioning-model=SPOT \
      --instance-termination-action=STOP \
      --boot-disk-size=30GB --boot-disk-type=pd-balanced \
      --network=main-vpc --subnet=primary-subnet \
      --scopes=cloud-platform \
      --tags=allow-iap-ssh \
      --quiet &
    # throttle creates to avoid API burst
    if (( i % DEPLOY_PARALLEL == DEPLOY_PARALLEL - 1 )); then wait; fi
  else
    gcloud compute instances start "$name" --zone="$ZONE" --project="$PROJECT" --quiet 2>/dev/null || true
  fi
done
wait

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
