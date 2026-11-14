#!/bin/bash
# 12:07Z container job: the 03:45 per-launch probability file, under the SINGLE-WRITER RULE (see forward_nightly.sh): if the VM's e5w: heartbeat
# is in results/timed_writes/<day>.log (today or yesterday PT), the VM writes tmp/e5/website/* and this does nothing. E5_CONTAINER_WRITERS=1 forces.
#    bash prereveal_writer.sh <scratchpad>
set -u; SP=$1; cd "$(dirname "$0")"; B=gs://usersim-bakeoff-347838016394/usersim_sim
TODAY=$(TZ=America/Los_Angeles date +%F); YDAY=$(TZ=America/Los_Angeles date -d yesterday +%F)
for d in $TODAY $YDAY; do
  if [ "${E5_CONTAINER_WRITERS:-0}" != 1 ] && gsutil cat $B/results/timed_writes/$d.log 2>/dev/null | grep -q "^e5w:"; then echo "VM writers live (e5w: heartbeat in results/timed_writes/$d.log): container 03:45 probability file skipped"; exit 0; fi
done
python prob_writer.py prereveal $TODAY $SP
