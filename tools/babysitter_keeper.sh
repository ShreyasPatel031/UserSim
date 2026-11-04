#!/bin/bash
# Babysitter keeper (Shreyas 22:57Z: "3 VMs running at every point of time ... spin up new ones, recycle IPs, change fingerprint").
# Every 60 s: each slot (VM name : port) must have a live pgql c32 run. A VM whose run ended (EXIT in its run log: block,
# browser-open failure, crash) or that is missing is deleted and recreated: new disk = new Camoufox fingerprint, new session
# on the port (sticky exit IP may rotate). Backoff per slot: 6 min after a long run, 15 min after a run that died in < 8 min.
S=/tmp/claude-0/-home-user-UserSim/985ad5f2-8c78-5e96-8903-dc657024cd94/scratchpad
B=gs://usersim-bakeoff-347838016394/usersim_sim/raw/_babysitter/pull
SLOTS="feeder-babysitter-1:10007 feeder-babysitter-2:10006 feeder-babysitter-3:10013"
declare -A made last_exit
log(){ echo "$(date -u +%H:%M:%S) $*"; }
create(){ # $1 vm $2 port
  gcloud compute instances delete $1 --zone us-central1-a --quiet >/dev/null 2>&1
  gsutil -q rm $B/run_$1.log 2>/dev/null
  if gcloud compute instances create $1 --zone us-central1-a --machine-type e2-standard-4 --image-family debian-12 --image-project debian-cloud \
      --network main-vpc --subnet primary-subnet --scopes storage-rw --metadata bsit-port=$2 --metadata-from-file startup-script=$S/bsit_vm2.sh \
      --labels owner=babysitter,purpose=people-c32 --quiet >/dev/null 2>&1; then made[$1]=$(date +%s); log "CREATED $1 port $2"; else log "CREATE FAILED $1 port $2"; fi; }
for s in $SLOTS; do made[${s%%:*}]=0; done  # VMs found already ended at start are recreated at once
while true; do
  live=$(gcloud compute instances list --filter="name~feeder-babysitter" --format="value(name)" 2>/dev/null)
  for s in $SLOTS; do vm=${s%%:*}; port=${s##*:}; now=$(date +%s)
    if ! echo "$live" | grep -qx $vm; then
      if [ "${made[$vm]}" = 0 ] || [ $(( now - ${made[$vm]} )) -ge 360 ]; then log "MISSING $vm"; create $vm $port; fi; continue; fi
    tail=$(gsutil -q cat $B/run_$vm.log 2>/dev/null | tail -2)
    if echo "$tail" | grep -q '^EXIT'; then
      age=$(( now - ${made[$vm]:-0} )); wait=360; [ $age -lt 480 ] && wait=900
      if [ -z "${last_exit[$vm]}" ] || [ "${last_exit[$vm]}" -lt "${made[$vm]}" ]; then last_exit[$vm]=$now; log "ENDED $vm port $port after $((age/60)) min ($(echo "$tail" | tr '\n' ' ' | cut -c1-120)); recreate in $((wait/60)) min"; fi
      if [ "${made[$vm]}" = 0 ] || [ $(( now - ${last_exit[$vm]} )) -ge $wait ]; then create $vm $port; fi
    fi
  done
  sleep 60
done
