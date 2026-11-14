#!/bin/bash
# Minute tick (review B4): the VM's Debian cron 3.0pl1 ignores CRON_TZ and the VM clock is UTC, so cron runs this every minute and it starts
# the jobs whose Pacific wall-clock time (America/Los_Angeles, DST-aware) equals the current minute in sched12a.txt. It also leaves a
# heartbeat (last tick, PT and UTC); at minute :01 it is copied to the bucket so a stopped cron is visible.
TW=/home/agent/w/tw12a; NOW=$(TZ=America/Los_Angeles date +%H:%M)
echo "$NOW PT $(date -u +%FT%TZ)" > $TW/last_tick
[ "${NOW:3:2}" = "01" ] && (gsutil -q cp $TW/last_tick gs://usersim-bakeoff-347838016394/usersim_sim/results/timed_writes/tick_12a.txt >/dev/null 2>&1 &)
awk -v t="$NOW" '$1 == t {print $2}' $TW/sched12a.txt | while read -r j; do (setsid bash $TW/run.sh "$j" >/dev/null 2>&1 < /dev/null &); done
exit 0
