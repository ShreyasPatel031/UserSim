#!/bin/bash
# Minute tick for bundle 12 (same mechanism as 12a's tick.sh): runs the sched12.txt entries whose Pacific HH:MM is now. Each entry's jobs run
# one after the other in one background chain (they depend on each other's outputs); "catchup" re-runs every listed job (each skips when done).
TW=/home/agent/w/tw; NOW=$(TZ=America/Los_Angeles date +%H:%M); echo "$NOW PT $(date -u +%FT%TZ)" > $TW/last_tick
[ "${NOW:3:2}" = "01" ] && (gsutil -q cp $TW/last_tick gs://usersim-bakeoff-347838016394/usersim_sim/results/timed_writes/tick_12.txt >/dev/null 2>&1 &)
awk -v t="$NOW" '$1 == t {$1=""; print}' $TW/sched12.txt | while read -r line; do
  ENVV=""; [[ "$line" == env:* ]] && { ENVV=${line%% *}; ENVV=${ENVV#env:}; line=${line#* }; }
  [[ "$line" == catchup* ]] && line=${line#catchup }
  (setsid bash -c "for j in $line; do env $ENVV bash $TW/tw.sh \$j; done" >/dev/null 2>&1 < /dev/null &)
done
exit 0
