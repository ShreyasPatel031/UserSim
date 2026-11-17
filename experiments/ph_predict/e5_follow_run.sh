#!/bin/bash
# Nightly logged input (orchestrator 05:00Z Nov 13): E5's follow_shadow.py (claude/person-model-v2 a754cb28) on the day's 00:05 line-up.
# Run after the 00:05 read exists (any timed run after 01:00 PT). No Product Hunt requests. Ids and counts only; the salt is read by
# the script, never printed. Writes gs://.../tmp/e5/follow_shadow/shadow_<D>.jsonl unless it already exists.
# usage: bash e5_follow_run.sh <YYYY-MM-DD> <work dir holding follow_shadow.py, store/, s/salt>
set -euo pipefail
D="$1"; W="$2"; B=gs://usersim-bakeoff-347838016394/usersim_sim
OUT="$B/tmp/e5/follow_shadow/shadow_$D.jsonl"
# also runs E5's team_shadow (e5_team_run.sh) at the end when its worktree exists (scratchpad/e5wt at aed7f324)
team() { WT="$(dirname "$W")/e5wt"; [ -d "$WT" ] && bash "$(dirname "$0")/e5_team_run.sh" "$D" "$W" "$WT" || echo "team_shadow: no worktree $WT"; }
# hunter reach at 00:05 (orchestrator 08:15Z Nov 17; SHADOW file only, no model reads it): raw/daily/<D>/hunter_reach_0005.json, written once
hunter() { HR="$B/raw/daily/$D/hunter_reach_0005.json"; gsutil -q stat "$HR" && { echo "hunter_reach exists"; return 0; }
  local ST="${E5_STORE:-$B/raw/population/store_v3}"; local G; G=$(gsutil stat "$ST/events.parquet" | awk '/Generation:/{print $2}'); local SDH="$W/store_$(basename "$ST")_$G"; mkdir -p "$SDH" "$W/s"
  gsutil -q -m cp -n "$ST/events.parquet" "$ST/persons.parquet" "$SDH/"; [ -s "$W/s/salt" ] || gsutil -q cp "$B/raw/population/_salt" "$W/s/salt"
  python3 "$(dirname "$0")/hunter_reach.py" "$B/raw/daily/$D/today_0005.json" "$D" "$SDH" "$W/s" "$W/hunter_reach_$D.json" && gsutil -q cp "$W/hunter_reach_$D.json" "$HR" && echo "wrote $HR"; }
gsutil -q stat "$B/raw/daily/$D/today_0005.json" && { hunter || echo "hunter_reach failed (shadow; does not block)"; }
if gsutil -q stat "$OUT"; then echo "exists $OUT"; team; exit 0; fi
gsutil -q stat "$B/raw/daily/$D/today_0005.json" || { echo "no 00:05 read for $D"; exit 1; }
mkdir -p "$W/store" "$W/s"
# store (orchestrator via E5 06:09Z Nov 13): E5's merged store until the population agent publishes the official merged one
# official merged store (orchestrator 11:49Z Nov 13); it is rewritten in place, so the local copy is keyed by events.parquet generation
STORE="${E5_STORE:-$B/raw/population/store_v3}"; GEN=$(gsutil stat "$STORE/events.parquet" | awk '/Generation:/{print $2}'); SD="$W/store_$(basename "$STORE")_$GEN"; mkdir -p "$SD"
gsutil -q -m cp -n "$STORE/events.parquet" "$STORE/persons.parquet" "$SD/"
[ -s "$W/s/salt" ] || gsutil -q cp "$B/raw/population/_salt" "$W/s/salt"
python3 -I "$W/follow_shadow.py" "$B/raw/daily/$D/today_0005.json" "$D" "$SD" "$W/s" "$W/out_$D.jsonl"
echo "{\"day\": \"$D\", \"store\": \"$STORE\", \"generation\": \"$GEN\", \"written_at\": \"$(date -u +%FT%TZ)\"}" | gsutil -q cp - "$B/tmp/e5/follow_shadow/shadow_$D.store.json"
gsutil -q cp "$W/out_$D.jsonl" "$OUT"; echo "wrote $OUT"
team
