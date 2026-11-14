#!/bin/bash
# 12:07Z container job: the 03:45 per-launch probability file, under the SINGLE-WRITER RULE (see forward_nightly.sh): if the VM's e5w: heartbeat
# is in results/timed_writes/<day>.log (today or yesterday PT), the VM writes tmp/e5/website/* and this does nothing. E5_CONTAINER_WRITERS=1 forces.
#    bash prereveal_writer.sh <scratchpad>
set -u; SP=$1; cd "$(dirname "$0")"; B=gs://usersim-bakeoff-347838016394/usersim_sim
TODAY=$(TZ=America/Los_Angeles date +%F); YDAY=$(TZ=America/Los_Angeles date -d yesterday +%F)
# today-rows fix date (deploy_today_rows.sh marker, bucket copy) -> per-day "fix pending" notes in the writers (same as tw.sh on the VM)
export TODAY_BUG_FIXED=$(gsutil cat gs://usersim-bakeoff-347838016394/usersim_sim/results/web/today_rows_fix.json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['fixed_from'])" 2>/dev/null)
for d in $TODAY $YDAY; do
  if [ "${E5_CONTAINER_WRITERS:-0}" != 1 ] && gsutil cat $B/results/timed_writes/$d.log 2>/dev/null | grep -q "^e5w:"; then echo "VM writers live (e5w: heartbeat in results/timed_writes/$d.log): container 03:45 probability file skipped"; exit 0; fi
done
python prob_writer.py prereveal $TODAY $SP
