#!/usr/bin/env bash
# Map IPRoyal pool file → daily vs historical roles (sizing: 3 daily + rest historical).
#   cp scripts/vm/iproyal.pool.example secrets/iproyal.pool   # fill with 5 purl paths
#   ./scripts/vm/ph_iproyal_daily_pool.sh plan
#   ./scripts/vm/ph_iproyal_daily_pool.sh apply-historical   # fleet slots from IP4+
#   ./scripts/vm/ph_iproyal_daily_pool.sh emit-daily-env     # env snippets for Data Feeder jobs
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
POOL="${PACE_IPROYAL_POOL:-$ROOT/secrets/iproyal.pool}"
OUT="$ROOT/results/ph_iproyal_limit/ip_pool_roles.tsv"
DAILY_N="${IPROYAL_DAILY_IPS:-2}"

read_pool() {
  [[ -f "$POOL" ]] || { echo "missing pool: $POOL (see scripts/vm/iproyal.pool.example)" >&2; exit 1; }
  mapfile -t lines < <(grep -v '^[[:space:]]*#' "$POOL" | grep -v '^[[:space:]]*$' || true)
  ((${#lines[@]} >= 1)) || { echo "empty pool $POOL" >&2; exit 1; }
}

cmd_plan() {
  read_pool
  mkdir -p "$(dirname "$OUT")"
  {
    echo -e "# index\trole\tpurl"
    local i=0
    for p in "${lines[@]}"; do
      i=$((i + 1))
      if ((i <= DAILY_N)); then
        case "$i" in
          1) role=daily_heavy ;;
          2) role=daily_people ;;
          *) role=daily_spare ;;
        esac
      else
        role="historical_$((i - DAILY_N))"
      fi
      echo -e "${i}\t${role}\t${p}"
    done
  } | tee "$OUT"
  echo "wrote $OUT (daily_ips=$DAILY_N total=${#lines[@]})"
}

_purl_abs() {
  local p=$1
  [[ "$p" = /* ]] && echo "$p" || echo "$ROOT/$p"
}

cmd_emit_daily_env() {
  read_pool
  cmd_plan >/dev/null
  local heavy people spare
  heavy="$(_purl_abs "${lines[0]}")"
  people="$(_purl_abs "${lines[1]:-${lines[0]}}")"
  spare="$(_purl_abs "${lines[2]:-${lines[1]:-${lines[0]}}}")"
  cat <<EOF
# Source on Data Feeder or daily job host (ISP Camoufox only — plain VM IP gets CF 403).
export PH_DAILY_PROXY_HEAVY='$heavy'
export PH_DAILY_PROXY_PEOPLE='$people'
export PH_DAILY_PROXY_SPARE='$spare'
export PH_DAILY_STRATEGY_ENV='$ROOT/scripts/vm/ph_strategies/iproyal/daily_steady.env'
EOF
}

cmd_apply_historical() {
  export PATH="/home/ubuntu/google-cloud-sdk/bin:${PATH:-}"
  # shellcheck source=/dev/null
  source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
  SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
  GC=(gcloud --account="$SA")
  read_pool
  local n_hist=$((${#lines[@]} - DAILY_N))
  ((n_hist >= 1)) || { echo "no historical IPs after reserving $DAILY_N daily" >&2; exit 1; }
  RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
  RUN_ID="${RUN_ID,,}"
  merge_one() {
    local level=$1 out="$ROOT/results/ph_iproyal_limit/strategy_${level}.env"
    mkdir -p "$(dirname "$out")"
    { cat "$ROOT/scripts/vm/ph_strategies/iproyal/_base.env"; echo; cat "$ROOT/scripts/vm/ph_strategies/iproyal/${level}.env"; } >"$out"
    echo "$out"
  }
  local strat hist_start=$((DAILY_N + 1)) slot=0 purl name
  strat="$(merge_one L3_mid)"
  FLEET_MIN_VMS=0 FLEET_MAX_VMS="$n_hist" PACE_FLEET_RUN_ID="$RUN_ID" PH_FLEET_STRATEGY="$strat" \
    bash "$ROOT/scripts/vm/ph_fleet_autoscale.sh" scale-to "$n_hist"
  for ((i = hist_start; i <= ${#lines[@]}; i++)); do
    slot=$((slot + 1))
    purl="$(_purl_abs "${lines[i-1]}")"
    [[ -f "$purl" ]] || { echo "missing $purl" >&2; exit 1; }
    name="feeder-fleet-${RUN_ID}-${slot}"
    if "${GC[@]}" compute instances describe "$name" --zone="${PACE_ZONE}" --format='value(status)' 2>/dev/null | grep -qx RUNNING; then
      "${GC[@]}" compute instances add-metadata "$name" --zone="${PACE_ZONE}" \
        --metadata-from-file="proxy-url=$purl,ph-strategy-env=$strat" >/dev/null
      echo "historical slot=$slot proxy=$purl"
    else
      echo "skip $name (not RUNNING)"
    fi
  done
  ONLY_SLOTS="$(seq -s, 1 "$n_hist")" PH_FLEET_STRATEGY_ENV="$strat" \
    bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh" | tail -5
}

case "${1:-plan}" in
  plan) cmd_plan ;;
  emit-daily-env) cmd_emit_daily_env ;;
  apply-historical) cmd_apply_historical ;;
  *) echo "usage: $0 plan|emit-daily-env|apply-historical" >&2; exit 1 ;;
esac
