#!/bin/bash
# 30-min person-pull quality check (population agent). Sync -> quality.py -> rows to GCS (handles stay there) -> counts-only
# report committed to docs/population/quality/<UTC>.md on claude/population-data. Prints FLAGS=<n>.
set -uo pipefail
W=${1:?work dir}; R=$W/raw; B=gs://usersim-bakeoff-347838016394/usersim_sim
REPO=$(cd "$(dirname "$0")/../.." && pwd); TS=$(date -u +%Y%m%dT%H%MZ); SINCE=${2:-2026-11-04T21:00:00Z}
exec 8>"$W/.quality.lock"; flock -n 8 || { echo "quality run already active"; exit 0; }
mkdir -p $R/people_live/vm $R/people_live/vm_pgql
gsutil -q -m rsync -d -x '.*(_code|logs|status|heartbeat|deep_list|claims)/.*|heartbeat.*' $B/raw/ph_population/people_live/vm/ $R/people_live/vm/
gsutil -q -m rsync -r -x '.*\.log$' $B/raw/ph_population/people_live/vm_pgql/ $R/people_live/vm_pgql/
mkdir -p $R/people_live/deep_list && gsutil -q -m rsync -d $B/raw/ph_population/people_live/vm/deep_list/ $R/people_live/deep_list/
mkdir -p $R/signedin_upvotes && gsutil -q -m rsync $B/raw/_babysitter/signedin_upvotes/ $R/signedin_upvotes/ 2>/dev/null
gsutil -q cp $B/raw/_pacetest/merged_ledger.txt $R/merged_ledger.txt 2>/dev/null || rm -f $R/merged_ledger.txt
gsutil -q cp $B/raw/population/requests/deep_list_latest.tsv $R/deep_list_latest.tsv 2>/dev/null
python3 "$REPO/tools/population/quality.py" $R "$SINCE" $W/quality_$TS.md $W/quality_$TS.jsonl > $W/quality_$TS.out
# pace-test output (raw/_pacetest/<vm>/<h>.json, not the store): scored with the same person definition, appended to the report
if gsutil -q ls $B/raw/_pacetest/ >/dev/null 2>&1; then
  rm -rf $W/pace; mkdir -p $W/pace/people_live/vm $W/pace/people_live/deep_list $W/pace/signedin_upvotes
  gsutil -q -m cp "$B/raw/_pacetest/*/*.json" $W/pace/people_live/vm/ 2>/dev/null
  gsutil -q -m cp "$B/raw/_pacetest/*/_signedin_upvotes/*.json" $W/pace/signedin_upvotes/ 2>/dev/null
  { echo; echo "# PACE TEST (raw/_pacetest/, not in the store)"; python3 "$REPO/tools/population/quality.py" $W/pace "$SINCE" /dev/null /dev/null | sed -n '/PERSON-LEVEL/,$p'; } >> $W/quality_$TS.md
fi
gsutil -q cp $W/quality_$TS.jsonl $B/raw/_babysitter/quality/$TS.jsonl
mkdir -p "$REPO/docs/population/quality"; cp $W/quality_$TS.md "$REPO/docs/population/quality/$TS.md"
(cd "$REPO" && git add docs/population/quality/$TS.md && git commit -q -m "population: person-pull quality report $TS (counts only)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WkCrUNzmycpWe5dkydHRnU" && timeout 60 git push -q origin claude/population-data)
cat $W/quality_$TS.out | tail -20
