#!/bin/bash
# Check -> end-to-end rehearsal (rehearse.sh, latest real day, DRY) -> deploy chain (orchestrator 04:23Z Nov 16: a fix deploys only after its check passes; the chain stops on any failed check).
# usage (on the VM, as agent): bash run_chain.sh deploy_h25|deploy     No pipes around the check: its exit code decides.
set -u; N=$(cd "$(dirname "$0")" && pwd); M=${1:?deploy_h25|deploy}
case "$M" in deploy_h25|deploy) ;; *) echo "usage: run_chain.sh deploy_h25|deploy"; exit 64;; esac
LOG=$(mktemp); bash "$N/deploy_nb.sh" check > "$LOG" 2>&1; rc=$?
tail -8 "$LOG"; rm -f "$LOG"
[ $rc -eq 0 ] || { echo "CHAIN STOPPED: check failed (rc $rc); nothing deployed"; exit 1; }
D=${REHEARSE_DAY:-$(TZ=America/Los_Angeles date +%F)}
bash "$N/rehearse.sh" "$D"; rc=$?
[ $rc -eq 0 ] || { echo "CHAIN STOPPED: end-to-end rehearsal on $D failed (rc $rc); nothing deployed"; exit 1; }
bash "$N/deploy_nb.sh" "$M"; rc=$?
[ $rc -eq 0 ] && echo "CHAIN OK: check passed, rehearsal passed on $D, $M deployed" || echo "CHAIN: $M failed (rc $rc); see output above"
exit $rc
