#!/usr/bin/env bash
# Nightly after the 00:00 PT close: reseed upvote slots in order
#   refresh_priority_<day> for the last N closed PT days (oldest first) -> upvotes_scroll_reread.txt -> every complete person, oldest upvotes read first.
# People already re-read by the upvote slots since tonight's close are dropped. Live feeds are not touched.
# Usage: ph_fleet_nightly_refresh_order.sh            # once, now
#        LOOP=1 ph_fleet_nightly_refresh_order.sh     # every night at RUN_AT_PT (default 00:10)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PACE_ENV_FILE="${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
source "$PACE_ENV_FILE"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
N_DAYS="${REFRESH_PRIORITY_N_DAYS:-4}"
ALL_COMPLETE_OBJ="usersim_sim/raw/_cursor/upvotes_refresh_complete_oldest_first.txt"
# Shreyas 2026-11-17: scroll re-read list holds only people who did not reach PH hasNextPage=false (filter script).
TAILS="${REFRESH_ORDER_TAILS:-usersim_sim/raw/_cursor/upvotes_scroll_reread.txt $ALL_COMPLETE_OBJ}"
UPVOTE_SLOTS="${UPVOTE_SLOTS:-9 27 38}"
RUN_AT_PT="${RUN_AT_PT:-0010}"

once() {
  local today days close_utc skip proj
  today="$(TZ=America/Los_Angeles date +%F)"
  days="$(for i in $(seq "$N_DAYS" -1 1); do TZ=America/Los_Angeles date -d "$today -$i day" +%F; done | xargs)"
  close_utc="$(date -u -d "TZ=\"America/Los_Angeles\" $today 00:00" +%Y-%m-%dT%H:%M:%SZ)"
  proj="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
  skip="$(mktemp)"
  for s in $UPVOTE_SLOTS; do
    n="feeder-fleet-${RUN_ID}-${s}"
    timeout 120 gcloud --account "usersim-cloud-agent@${proj}.iam.gserviceaccount.com" compute scp \
      "$n:/opt/ph/reuse/status_$n.jsonl" "/tmp/refresh_order_st_$s.jsonl" \
      --zone="$PACE_ZONE" --project="$proj" --tunnel-through-iap --quiet >/dev/null 2>&1 || true
  done
  CLOSE_UTC="$close_utc" SLOTS="$UPVOTE_SLOTS" python3 - >"$skip" <<'PY'
import json, os
close = os.environ["CLOSE_UTC"]
done = set()
for s in os.environ["SLOTS"].split():
    try:
        f = open(f"/tmp/refresh_order_st_{s}.jsonl")
    except OSError:
        continue
    for ln in f:
        try:
            j = json.loads(ln)
        except Exception:
            continue
        if (j.get("rc") == 0 and j.get("handle") and (j.get("utc") or "") >= close
                and (j.get("coverage") or {}).get("upvotes") is not None
                and not str(j.get("method") or "").startswith("pfull")):
            done.add(j["handle"].lower().lstrip("@"))
print("\n".join(sorted(done)))
PY
  local all_tmp
  all_tmp="$(mktemp -d)"
  gcloud storage cp -q "gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/have_index.jsonl" "$all_tmp/hi.jsonl"
  python3 - "$all_tmp/hi.jsonl" >"$all_tmp/all.txt" <<'PY'
import json, sys
rows = []
for ln in open(sys.argv[1]):
    try:
        j = json.loads(ln)
    except Exception:
        continue
    h = (j.get("handle") or "").lower().lstrip("@")
    if h and j.get("complete"):
        rows.append((((j.get("tabs") or {}).get("upvotes") or {}).get("last_pulled_at") or "", h))
print("\n".join(h for _, h in sorted(rows)))
PY
  gcloud storage cp -q "$all_tmp/all.txt" "gs://${MVP_GCS_BUCKET}/${ALL_COMPLETE_OBJ}"
  rm -rf "$all_tmp"
  echo "=== refresh order $(date -u +%FT%TZ): days=[$days] close=$close_utc skip=$(grep -c . "$skip" || true)"
  REFRESH_PRIORITY_DAYS="$days" REFRESH_TAIL_GCS="$TAILS" REFRESH_SKIP_FILE="$skip" UPVOTE_SLOTS="$UPVOTE_SLOTS" \
    bash "$ROOT/scripts/vm/ph_fleet_apply_refresh_priority.sh"
  rm -f "$skip"
}

if [[ "${LOOP:-0}" != 1 ]]; then
  once
  exit 0
fi
last=""
[[ "${SKIP_TODAY:-0}" == 1 ]] && last="$(TZ=America/Los_Angeles date +%F)"
while true; do
  d="$(TZ=America/Los_Angeles date +%F)"
  if [[ "$(TZ=America/Los_Angeles date +%H%M)" > "$RUN_AT_PT" || "$(TZ=America/Los_Angeles date +%H%M)" == "$RUN_AT_PT" ]] && [[ "$d" != "$last" ]]; then
    once 2>&1 | tee -a "$ART/nightly_refresh_order.log" || echo "refresh order FAILED $(date -u +%FT%TZ)" | tee -a "$ART/nightly_refresh_order.log"
    last="$d"
  fi
  sleep 120
done
