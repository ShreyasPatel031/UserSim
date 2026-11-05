#!/bin/bash
# Babysitter keeper (Shreyas 22:57Z: "3 VMs running at every point of time ... spin up new ones, recycle IPs, change fingerprint").
# Every 60 s: each slot (VM name : port) must have a live pgql c32 run. A VM whose run ended (EXIT in its run log: block,
# browser-open failure, crash) or that is missing is deleted and recreated: new disk = new Camoufox fingerprint, new session
# on the port (sticky exit IP may rotate). Backoff per slot: 6 min after a long run, 15 min after a run that died in < 8 min.
S=/tmp/claude-0/-home-user-UserSim/985ad5f2-8c78-5e96-8903-dc657024cd94/scratchpad
B=gs://usersim-bakeoff-347838016394/usersim_sim/raw/_babysitter/pull
SLOTS="feeder-babysitter-1:10007:pfull_vm.sh feeder-babysitter-2:10006:pfull_vm.sh feeder-babysitter-3:10013:pfull_vm.sh feeder-babysitter-4:10018:pfull_vm.sh feeder-babysitter-5:10019:pfull_vm.sh feeder-babysitter-6:10020:pfull_vm.sh feeder-babysitter-deep-1:10014:pdeep_vm.sh feeder-babysitter-deep-2:10015:pdeep_vm.sh feeder-babysitter-deep-3:10016:pdeep_vm.sh feeder-babysitter-deep-4:10017:pdeep_vm.sh"
declare -A made last_exit
log(){ echo "$(date -u +%H:%M:%S) $*"; }
create(){ # $1 vm $2 port $3 startup script
  gcloud compute instances delete $1 --zone us-central1-a --quiet >/dev/null 2>&1
  gsutil -q rm $B/run_$1.log 2>/dev/null
  if gcloud compute instances create $1 --zone us-central1-a --machine-type e2-standard-4 --image-family debian-12 --image-project debian-cloud \
      --network main-vpc --subnet primary-subnet --scopes storage-rw --metadata bsit-port=$2 --metadata-from-file startup-script=$S/$3 \
      --labels owner=babysitter,purpose=people-c32 --quiet >/dev/null 2>&1; then made[$1]=$(date +%s); log "CREATED $1 port $2"; else log "CREATE FAILED $1 port $2"; fi; }
for s in $SLOTS; do made[${s%%:*}]=0; done  # VMs found already ended at start are recreated at once
while true; do
  live=$(gcloud compute instances list --filter="name~feeder-babysitter" --format="value(name)" 2>/dev/null)
  for s in $SLOTS; do IFS=: read vm port scr <<< "$s"; now=$(date +%s)
    if ! echo "$live" | grep -qx $vm; then
      if [ "${made[$vm]}" = 0 ] || [ $(( now - ${made[$vm]} )) -ge 360 ]; then log "MISSING $vm"; create $vm $port $scr; fi; continue; fi
    tail=$(gsutil -q cat $B/run_$vm.log 2>/dev/null | tail -2)
    [ "${made[$vm]}" = 0 ] && { ct=$(gcloud compute instances describe $vm --zone us-central1-a --format="value(creationTimestamp)" 2>/dev/null); [ -n "$ct" ] && made[$vm]=$(date -d "$ct" +%s); }
    lu=$(gsutil ls -l gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_population/people_live/vm/status/$vm.jsonl 2>/dev/null | awk 'NR==1{print $2}')
    if [ -n "$lu" ] && [ "${made[$vm]}" != 0 ] && [ $(( now - ${made[$vm]} )) -gt 1200 ] && [ $(( now - $(date -d "$lu" +%s) )) -gt $( [[ $vm == *deep* ]] && echo 2700 || echo 720 ) ] && ! echo "$tail" | grep -q '^EXIT'; then
      log "STALLED $vm (no status row for 12 min fast / 45 min deep); recreating"; create $vm $port $scr; continue; fi
    if echo "$tail" | grep -q '^EXIT'; then
      age=$(( now - ${made[$vm]:-0} )); wait=360; [ $age -lt 480 ] && wait=900
      if [ -z "${last_exit[$vm]}" ] || [ "${last_exit[$vm]}" -lt "${made[$vm]}" ]; then last_exit[$vm]=$now; log "ENDED $vm port $port after $((age/60)) min ($(echo "$tail" | tr '\n' ' ' | cut -c1-120)); recreate in $((wait/60)) min"; fi
      if [ "${made[$vm]}" = 0 ] || [ $(( now - ${last_exit[$vm]} )) -ge $wait ]; then create $vm $port $scr; fi
    fi
  done
  sleep 60
done
